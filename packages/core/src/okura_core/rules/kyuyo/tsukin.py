"""通勤手当の非課税（所得税法第9条第1項第5号、同施行令第20条の2、同施行規則第2条の2）の純粋関数（規則モジュール kyuyo）。

限度額の版は「受けるべき日」（支給日。差額の追給は元の支給日）で選ぶ（年分では選ばない）：
docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md#2.3。版はパラメータ 所得税.通勤手当の非課税限度額.版 の子。

計算の単位は「受給者 × 支払者 × 月」（質疑応答事例 03/21：その月中に支給する通勤手当の合計額のうち、限度額に達するまで）。
入力が足りないとき（通勤の状況・合理的な運賃の判断がない）は限度額を幅（下端 0）で返し、inputs.py が単調な判断の両端で評価する（D21 R6、tsukin HT5）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...basis import SourceKind
from ...rounding import RoundingRule

P_ROOT = "所得税.通勤手当の非課税限度額"
#: 距離の区分の並び（パラメータの子の名前。短い順）。
ROW_KEYS: tuple[str, ...] = (
    "2km以上10km未満",
    "10km以上15km未満",
    "15km以上25km未満",
    "25km以上35km未満",
    "35km以上45km未満",
    "45km以上55km未満",
    "55km以上65km未満",
    "65km以上75km未満",
    "75km以上85km未満",
    "85km以上95km未満",
    "95km以上",
)
#: 版の並び（適用開始日の早い順。先頭は「改正前」で適用開始日を持たない）。
VERSION_KEYS: tuple[str, ...] = ("改正前", "令和7年4月以後", "令和8年4月以後")

#: 駐車場等料金相当額の1円未満（施行規則第2条の2 に端数の定めがなく、国税庁の Q&A の例が切上げ。D21 R5 の「国税庁の説明」）。
PARKING_CEIL = RoundingRule(
    name="ceil_yen_commuting_parking",
    title="駐車場等料金相当額の1円未満の端数を切り上げる",
    function="ceil",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="通勤手当の非課税限度額の改正に関するＱ＆Ａ（令和8年4月）Q3-3 例2「2,182 円（1,200 円／11 枚×20 日）（１円未満端数切上げ）」",
    references=(
        "docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md#3",
        "docs/public-sources/20261111_impl-research_tsukin-laws-and-nta.md#4.4",
    ),
)


@dataclass(frozen=True)
class Row:
    """第2号の距離の区分の1行。lower 以上 upper 未満（upper が None なら上限なし）。"""

    key: str
    lower: Fraction
    upper: Fraction | None
    amount: int

    def contains(self, km: Fraction) -> bool:
        return km >= self.lower and (self.upper is None or km < self.upper)


@dataclass(frozen=True)
class Version:
    """施行令第20条の2 の1つの版の値。from_on は適用開始の受けるべき日（改正前は None）。"""

    key: str
    from_on: _dt.date | None
    cap: int
    parking_cap: int
    rows: tuple[Row, ...]

    @property
    def min_km(self) -> Fraction:
        return self.rows[0].lower

    @property
    def max_amount(self) -> int:
        return max(r.amount for r in self.rows)

    def amount_for(self, km: Fraction) -> int | None:
        """片道の距離の第2号の金額（2km 未満は None）。"""
        for r in self.rows:
            if r.contains(km):
                return r.amount
        return None

    def parameter_names(self, *, row: Row | None = None) -> tuple[str, ...]:
        base = f"{P_ROOT}.版.{self.key}"
        names = [f"{base}.交通機関等の上限", f"{base}.駐車場等料金相当額の上限"]
        if self.from_on is not None:
            names.append(f"{base}.適用開始日")
        if row is not None:
            names.append(f"{base}.金額.{row.key}")
            names.append(f"{P_ROOT}.距離の区分.{row.key}.以上")
            if row.upper is not None:
                names.append(f"{P_ROOT}.距離の区分.{row.key}.未満")
        return tuple(names)


def versions_from_parameters(p: Any) -> tuple[Version, ...]:
    """parameters(期間)（1月1日の ParameterNodeAtInstant）から版の並びを作る。"""
    node = p.所得税.通勤手当の非課税限度額
    bands = []
    for key in ROW_KEYS:
        b = getattr(node.距離の区分, key)
        lower = Fraction(b.以上)
        upper = None if key == ROW_KEYS[-1] else Fraction(b.未満)
        bands.append((key, lower, upper))
    versions = []
    for vkey in VERSION_KEYS:
        v = getattr(node.版, vkey)
        from_on = None if vkey == VERSION_KEYS[0] else _dt.date.fromisoformat(v.適用開始日)
        rows = tuple(Row(k, lo, hi, int(getattr(v.金額, k))) for k, lo, hi in bands)
        versions.append(Version(vkey, from_on, int(v.交通機関等の上限), int(v.駐車場等料金相当額の上限), rows))
    return tuple(versions)


def version_for(versions: Iterable[Version], on: _dt.date) -> Version:
    """受けるべき日 on に適用される版（適用開始日がそれ以前の最後の版。先頭の版は改正前）。"""
    chosen: Version | None = None
    for v in versions:
        if v.from_on is None or v.from_on <= on:
            chosen = v
    if chosen is None:
        raise ValueError("通勤手当の版がない")
    return chosen


# ---------------------------------------------------------------------------
# 駐車場等料金相当額（施行規則第2条の2 第2項）
# ---------------------------------------------------------------------------


def parking_monthly(parkings: Iterable[Mapping[str, Any]], version: Version) -> tuple[int, tuple[str, ...]]:
    """駐車場等料金相当額（要件を満たす駐車場等の合計、上限つき）。途中は有理数で計算し、1円未満は名前つきの規則で切り上げる。"""
    if version.parking_cap == 0:
        return 0, ()
    total = Fraction(0)
    rounded: list[str] = []
    for lot in parkings:
        if lot["location"] not in ("near_workplace", "near_transit_facility"):
            continue  # 自宅付近などは要件を満たさない（施行規則第2条の2 第1項、Q&A Q2-4）
        total += _lot_monthly(lot)
    if total.denominator != 1:
        rounded.append(PARKING_CEIL.name)
    return min(PARKING_CEIL.apply(total), version.parking_cap), tuple(rounded)


def _lot_monthly(lot: Mapping[str, Any]) -> Fraction:
    fee = Fraction(lot["fee"])
    unit = lot["fee_unit"]
    multiple = max(1, lot.get("fee_unit_multiple", 1))
    if unit == "month":
        return fee / multiple
    if unit == "year":
        return fee / (12 * multiple)
    if unit == "per_use":
        return fee * lot["uses_per_month"]
    return fee * 365 / lot["fee_period_days"] / 12  # 第2項第4号（料金の額×365÷算定の基礎となった期間の日数÷12）


# ---------------------------------------------------------------------------
# 1か月の限度額
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Limit:
    """1か月の限度額の下端・上端と、合理的な運賃の判断が要るか（要れば下端と上端が違う）。

    used_row は第2号の金額を使ったときの距離の区分（根拠に使う）。
    split は、合理的な運賃の未入力とは別に、一次情報で決まらない当て方（月の中途の交通手段の変更）か、
    国税庁の「差し支えない」取扱い（障害者の 2km 未満の自動車通勤）の当てはめが入力で決まらないために下端と上端が違うこと
    （inputs.py が読みの分かれ目 判断.通勤手当の限度の当て方 の両端で評価する。D21 R6・D22 S1）。
    """

    low: int
    high: int
    needs_fare: bool = False
    used_row: Row | None = None
    split: bool = False

    @property
    def exact(self) -> bool:
        return self.low == self.high


def monthly_limit(
    status: Mapping[str, Any] | None, fare: int | None, version: Version, *, disabled: bool = False, special: bool | None = None
) -> Limit:
    """1か月の限度額（所得税法施行令第20条の2 の号の区分）。

    status：通勤の状況の記録（commuting_status）の attributes。None なら入力がない（HT5：0 から交通機関等の上限まで）。
    fare：最も経済的かつ合理的な経路及び方法による1か月当たりの運賃等の額（判断）。None なら未入力。
    disabled：その月に障害者（disability_basis）か。交通用具の片道 2km 未満は第2号の対象外（全額課税）だが、障害者が特別の事情で
    自動車を使うときは、交通機関を利用したとした場合の合理的な運賃の額を限度額として「差し支えありません」（質疑応答事例 03/18）。
    special：判断.障害者の通勤の特別の事情（2026-11-12 に語彙を足した）。true なら合理的な運賃の額（未入力なら判断の分かれ目）を限度額、
    false なら全額課税。None（未入力・食い違い）なら 0（全額課税）と合理的な運賃の額（未入力なら交通機関等の上限）を両端にする（split）。
    """
    if status is None:
        if fare is None:
            return Limit(0, version.cap, needs_fare=True)
        v = min(fare, version.cap)  # 通勤の状況がなくても、合理的な運賃の判断があれば交通機関の号として扱う
        return Limit(v, v)
    means = status["means"]
    if means == "transit":
        if fare is None:
            return Limit(0, version.cap, needs_fare=True)
        v = min(fare, version.cap)
        return Limit(v, v)
    km = _km(status)
    amount = version.amount_for(km)
    parking, _ = parking_monthly(status.get("parkings", ()), version)
    row = next((r for r in version.rows if r.contains(km)), None)
    if means == "vehicle":
        if amount is None:  # 2km 未満：第2号の対象外（全額課税。駐車場等も同じ：Q&A Q3-4）
            if disabled and special is True:
                if fare is None:
                    return Limit(0, version.cap, needs_fare=True)
                v = min(fare, version.cap)
                return Limit(v, v)
            if disabled and special is None:
                return Limit(0, version.cap if fare is None else min(fare, version.cap), needs_fare=fare is None, split=True)
            return Limit(0, 0)
        return Limit(amount + parking, amount + parking, used_row=row)
    # 併用（改正前・R7 第4号、R8 第5号・第6号）。交通用具の距離が 2km 未満なら交通機関の号（第1号・第4号）
    vehicle = 0 if amount is None else amount + parking
    if fare is None:
        return Limit(min(vehicle, version.cap), version.cap, needs_fare=True, used_row=row)
    return Limit(min(fare + vehicle, version.cap), min(fare + vehicle, version.cap), used_row=row)


def mixed_limit(limits: Iterable[Limit]) -> Limit:
    """同じ支払者の同じ月に交通手段の違う通勤の状況が重なるときの1か月の限度額。

    月の中途の変更の当て方の一次情報は距離の変更（質疑応答事例 03/20「特段の規定はありません」、長い方の距離で差し支えない）だけで、
    交通手段の変更は見つからない（docs の tsukin §4.4）。D21 R6・D22 S1 により、それぞれの交通手段の号の限度額の全部を候補にし、
    下端（候補の下端の最小）と上端（候補の上端の最大）で評価する（split。読みの分かれ目の両端）。
    """
    items = list(limits)
    if not items:
        raise ValueError("限度額の候補がない")
    low = min(x.low for x in items)
    high = max(x.high for x in items)
    used = max(items, key=lambda x: (x.high, x.low)).used_row
    return Limit(low, high, needs_fare=any(x.needs_fare for x in items), used_row=used, split=low != high or any(x.split for x in items))


def _km(status: Mapping[str, Any]) -> Fraction:
    v = status["one_way_km"]
    return Fraction(v["num"], v["den"])


# ---------------------------------------------------------------------------
# 非課税の額（受給者 × 支払者 × 月の単位。読みの分かれるところは取りうる全部）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """1回の支払の通勤手当（現金と現物の定期券の合計）。limit はその支払の版と状況の1か月の限度額。months は対象の月数。"""

    allowance: int
    limit: int
    months: int
    payer: str
    due_ym: tuple[int, int]
    paid_ym: tuple[int, int]


def _total(items: Iterable[Item], key: Callable[[Item], Any], multi: bool) -> int:
    cells: dict[Any, list[Item]] = {}
    for item in items:
        cells.setdefault(key(item), []).append(item)
    total = 0
    for cell in cells.values():
        allowance = sum(i.allowance for i in cell)
        limit = max(i.limit * (i.months if multi else 1) for i in cell)
        total += min(allowance, limit)
    return total


#: 読みの分かれるところ（UT2：支払者ごとか合計か、UT3：支給すべき月か支給を受けた月か）の組。
_READINGS: tuple[Callable[[Item], Any], ...] = (
    lambda i: (i.payer, i.due_ym),
    lambda i: (i.payer, i.paid_ym),
    lambda i: i.due_ym,
    lambda i: i.paid_ym,
)


def nontaxable_bounds(items: Iterable[Item]) -> tuple[int, int]:
    """非課税の額の最小と最大（読みの分かれるところの全部：UT1 月数・UT2 支払者・UT3 月）。分かれなければ同じ値。"""
    rows = list(items)
    if not rows:
        return 0, 0
    multis = (False, True) if any(i.months > 1 for i in rows) else (False,)
    totals = [_total(rows, key, m) for key in _READINGS for m in multis]
    return min(totals), max(totals)

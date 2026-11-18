"""不動産所得の損失のうち、不動産所得の計算（所法26②）と損益通算（所法69①）の上で生じなかったものとみなす金額（IK-104。2026-11-12）。

- 組合事業・信託（租税特別措置法第41条の4の2、同施行令第26条の6の2）：特定組合員（組合事業の重要業務のすべての執行の決定に関与し、かつ重要な部分の
  すべてを自ら執行している組合員以外の組合員。業務の執行の全部を委任していれば特定組合員）又は特定受益者（信託の受益者）の、組合事業・信託ごとの
  不動産所得の総収入金額の合計額が必要経費の合計額に満たない部分。他の不動産所得の黒字とも通算しない（TA1391・TA2250（注4））。
- 国外中古建物（措法第41条の4の3、措令第26条の6の3、措規第18条の24の2）：国外にある中古の建物で、耐用年数を簡便法（耐用年数省令3①二）か、書類で確かめられない
  見積り（3①一）で算定したもの。建物ごとの損失のうち償却費に相当する部分（損失が償却費を超えれば償却費、以下なら損失：措令26の6の3①）の合計から、
  国外不動産等（国外中古建物以外の国外の不動産等）の貸付けの所得があればその所得から「損失が償却費以上の建物の、損失−償却費の合計」を控除した額
  （負なら0）を控除する（②）。物件ごとの区分（③一・二）と共通の必要経費の配分（③三）は記録の物件（property_id）による。
- 土地等の負債の利子（措法41の4）との関係：組合事業・信託の業務の区分ごとに、利子の額のうち生じなかったものとみなされる金額を超える部分だけを
  土地等の負債の利子とする（措通41の4−4）。国外中古建物の分は償却費に限るので、利子とは重ならない（法令の読み：basis.RENTAL_SPECIAL_LAND_RULE）。
- 根拠：docs/public-sources/20261112_impl-research5_fudosan-special-losses.md。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

DOMESTIC = "domestic"  # 国内の物件（組合事業・信託でない）
FOREIGN_USED = "foreign_used_building"  # 国外中古建物
FOREIGN_OTHER = "foreign_other"  # 国外不動産等（国外中古建物以外の国外の不動産等）
ARRANGEMENT = "arrangement"  # 組合事業・信託

PARTNERSHIP_UNATTRIBUTED_REASON = (
    "入力の不足：組合事業・信託の物件（rental_property の held_through）か国外中古建物がある人の不動産所得に、物件（property_id）に結びつかない"
    "収入・必要経費・減価償却費がある（組合事業・信託ごと・国外中古建物ごとに損失を計算する：措令26の6の2④・26の6の3③。共通の必要経費は"
    "合理的な基準で配分して物件ごとの記録にする）"
)
PARTNERSHIP_ARRANGEMENT_REASON = (
    "入力の不足：組合事業・信託の物件（rental_property の held_through）に組合契約・信託の識別（arrangement_id）がない"
)
FOREIGN_USED_METHOD_REASON = (
    "入力の不足：国外にある中古の建物の耐用年数の決め方（判断.減価償却の区分 の useful_life_method。見積りなら remaining_life_documented も）がない"
    "（国外中古建物に当たるかが決まらない：措法41の4の3②一・措規18の24の2①）"
)
FOREIGN_USED_CLASS_REASON = (
    "入力の不足：国外の賃貸物件の中古の減価償却資産が建物かどうか（判断.減価償却の区分 の asset_class）がない（国外中古建物に当たるかが決まらない）"
)


@dataclass(frozen=True)
class Unit:
    """不動産所得の区分の1単位（物件）の収支。kind は DOMESTIC・FOREIGN_USED・FOREIGN_OTHER・ARRANGEMENT。
    arrangement は組合事業・信託の識別、specified は特定組合員・特定受益者に当たるか（組合事業・信託のときだけ）。
    building_dep は国外中古建物の償却費（その建物の分だけ）。"""

    key: str
    kind: str
    net: int
    building_dep: int = 0
    arrangement: str | None = None
    specified: bool = False


@dataclass(frozen=True)
class Deemed:
    """生じなかったものとみなす金額（組合事業・信託の分の組合ごとの額、国外中古建物の分）。"""

    by_arrangement: Mapping[str, int]
    foreign: int

    @property
    def total(self) -> int:
        return sum(self.by_arrangement.values()) + self.foreign


def arrangement_losses(units: Iterable[Unit]) -> dict[str, int]:
    """措令26の6の2④：特定組合員・特定受益者の、組合事業・信託ごとの総収入金額の合計が必要経費の合計に満たない部分。"""
    nets: dict[str, int] = {}
    for u in units:
        if u.kind == ARRANGEMENT and u.specified and u.arrangement is not None:
            nets[u.arrangement] = nets.get(u.arrangement, 0) + u.net
    return {a: -n for a, n in sorted(nets.items()) if n < 0}


def foreign_used_loss(units: Iterable[Unit]) -> int:
    """措法41の4の3②二・措令26の6の3①②：国外不動産所得の損失の金額。

    計算例（docs/inferences/20261112_impl-research5_fudosan-special-cases.md）：建物A 損失 300・償却費 200、建物B 損失 50・償却費 100、
    国外不動産等の所得 150 → ①の合計 200＋50＝250、②の控除 150−(300−200)＝50 → 200。
    """
    units = list(units)
    first = 0  # ①の合計
    excess = 0  # ②二イ−ロ（損失が償却費以上の建物の、損失−償却費の合計）
    for u in units:
        if u.kind != FOREIGN_USED or u.net >= 0:
            continue
        loss = -u.net
        dep = max(0, u.building_dep)
        if dep > loss:
            first += loss  # ①一
        else:
            first += dep  # ①二
            excess += loss - dep
    other = sum(u.net for u in units if u.kind == FOREIGN_OTHER)
    reduce = max(0, other - excess) if other > 0 else 0  # ②：国外不動産等の貸付けによる不動産所得の金額がある場合
    return max(0, first - reduce)


def deemed(units: Iterable[Unit]) -> Deemed:
    units = list(units)
    return Deemed(arrangement_losses(units), foreign_used_loss(units))


def land_interest_after_arrangements(land_by_arrangement: Mapping[str, int], deemed_by_arrangement: Mapping[str, int]) -> int:
    """措通41の4−4：組合事業・信託の業務の区分ごとに、土地等の負債の利子の額のうち生じなかったものとみなされる金額を超える部分（以下なら0）。
    返すのは、組合事業・信託の分の土地等の負債の利子から差し引く額の合計。"""
    return sum(min(v, deemed_by_arrangement.get(a, 0)) for a, v in land_by_arrangement.items())


__all__ = [
    "ARRANGEMENT",
    "DOMESTIC",
    "Deemed",
    "FOREIGN_OTHER",
    "FOREIGN_USED",
    "FOREIGN_USED_CLASS_REASON",
    "FOREIGN_USED_METHOD_REASON",
    "PARTNERSHIP_ARRANGEMENT_REASON",
    "PARTNERSHIP_UNATTRIBUTED_REASON",
    "Unit",
    "arrangement_losses",
    "deemed",
    "foreign_used_loss",
    "land_interest_after_arrangements",
]

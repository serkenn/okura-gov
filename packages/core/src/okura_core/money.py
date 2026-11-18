"""金額と率（D21 R5・D22 S3、SCOPE §8）。

- 金額の最終の値は整数の円（Python の int。bool は受け付けない）。
- 途中の値は有理数（fractions.Fraction）。float は受け付けない（float32・float64 で1円ずれる：
  docs/measurements/20261109_impl-prep_tools-openfisca-probe.md §6）。
- 率は Fraction（中間表現の {"num", "den"} から作る）。
- 根拠のない端数を候補の全部で評価して金額だけが違うときは、幅（YenRange）で返す（D22 S3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

#: OpenFisca の int の変数（numpy.int32）に入れられる上限。超える金額は渡さず「対象外」にする。
INT32_MAX = 2**31 - 1

Exact = int | Fraction


def require_yen(value: Any, *, what: str = "金額") -> int:
    """整数の円であることを確かめて返す（bool・float・文字列を拒否）。"""
    if type(value) is not int:
        raise TypeError(f"{what}は整数の円が必要（{type(value).__name__} が来た）")
    return value


def to_fraction(value: Any) -> Fraction:
    """int と Fraction だけを Fraction にする（float・bool・文字列を拒否）。"""
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, Fraction):
        return value
    raise TypeError(f"有理数にできるのは int と Fraction だけ（{type(value).__name__} が来た）")


def rate(num: int, den: int) -> Fraction:
    """率（分子・分母の整数）を Fraction にする。"""
    require_yen(num, what="率の分子")
    require_yen(den, what="率の分母")
    if den <= 0:
        raise ValueError("率の分母は1以上")
    return Fraction(num, den)


def rate_from_ir(obj: Any) -> Fraction:
    """中間表現の率 {"num": 整数, "den": 1以上の整数} を Fraction にする。"""
    if not isinstance(obj, dict) or set(obj) != {"num", "den"}:
        raise ValueError('率は {"num": 整数, "den": 整数} の形')
    return rate(obj["num"], obj["den"])


def times_rate(amount: Exact, r: Fraction) -> Fraction:
    """金額 × 率（丸めない。丸めは rounding.py の名前つきの関数で行う）。"""
    return to_fraction(amount) * r


@dataclass(frozen=True)
class YenRange:
    """金額の幅（両端を含む、整数の円）。根拠のない端数を候補で評価したときの結果（D22 S3）。"""

    min: int
    max: int

    def __post_init__(self) -> None:
        require_yen(self.min, what="幅の下端")
        require_yen(self.max, what="幅の上端")
        if self.min > self.max:
            raise ValueError("幅の下端が上端より大きい")

    @property
    def is_exact(self) -> bool:
        return self.min == self.max

    def to_dict(self) -> dict[str, Any]:
        return {"type": "yen_range", "min": self.min, "max": self.max}

    @classmethod
    def of(cls, values: list[int] | tuple[int, ...]) -> YenRange:
        if not values:
            raise ValueError("候補が空")
        return cls(min(values), max(values))

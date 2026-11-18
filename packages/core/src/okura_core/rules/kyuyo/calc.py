"""給与所得の金額（所得税法第28条、租税特別措置法第29条の4第2項）の純粋関数（規則モジュール kyuyo）。

OpenFisca の変数 所得税_給与所得 の式と、結果の根拠の組み立ての両方がこの関数を使う（規則の置き場所は1か所）。

年分ごとの規則（docs/hypotheses/20261109_impl-prep_kyuyo-hypotheses.md H1。根拠は各パラメータのメタデータ）：
  1. 措置法第29条の4第2項が適用される年分（令和8年分・令和9年分）で、収入金額が第1号の下限以上・第5号の上限未満：
     その号の金額（所得税法第28条第2項から第4項までより優先）。
  2. それ以外で、収入金額が660万円未満：その年分の版の別表第五（所得税法第28条第4項）。
  3. 660万円以上：第28条第2項・第3項（収入金額 − 給与所得控除額）。1円未満は名前つきの規則
     rounding.KYUYO_SHOTOKU_660MAN_FLOOR で切り捨てる。
収入金額は、その年中の給与等の合計（支払者が複数でも合計に1回だけ当てる。所法28④、kyuyo H7）。
年末調整の経過措置（旧の表）は確定申告の値には使わない（kyuyo H3。パラメータ 所得税.給与所得.別表第五 のメタデータ）。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...rounding import KYUYO_SHOTOKU_660MAN_FLOOR, RoundingRule
from .tables import Beppyo5Row, Beppyo5Table, load_beppyo5

P_TABLE = "所得税.給与所得.別表第五"
P_TABLE_UPPER = "所得税.給与所得.別表第五を使う収入の上限"
P_SOCHI = "所得税.給与所得.措法第29条の4第2項"
P_SOCHI_APPLIES = f"{P_SOCHI}.適用"
P_DEDUCTION = "所得税.給与所得控除額"
P_SOCHI1 = "所得税.給与所得.措法第29条の4第1項"


class KyuyoPath(enum.Enum):
    """給与所得の金額を決めた規定。"""

    SOCHI_29_4_2 = "租税特別措置法第29条の4第2項"
    BEPPYO5 = "所得税法第28条第4項・別表第五"
    ART28_2_3 = "所得税法第28条第2項・第3項"


@dataclass(frozen=True)
class SochiBracket:
    """措置法第29条の4第2項の1号。kind：zero・fixed（給与所得の金額）、minus（収入金額 − 控除額）。"""

    number: int
    lower: int
    upper: int
    kind: str
    amount: int

    def contains(self, x: int) -> bool:
        return self.lower <= x < self.upper

    def value(self, x: int) -> int:
        if self.kind == "minus":
            return x - self.amount
        return self.amount

    def parameter_names(self) -> tuple[str, ...]:
        last = "控除額" if self.kind == "minus" else "給与所得"
        base = f"{P_SOCHI}.第{self.number}号"
        return (f"{base}.以上", f"{base}.未満", f"{base}.{last}")


@dataclass(frozen=True)
class DeductionBracket:
    """所得税法第28条第3項の1区分：above 超 up_to 以下（up_to が None なら上限なし）で、base + (x − above) × rate。"""

    key: str
    above: int
    up_to: int | None
    base: int
    rate: Fraction | None

    def contains(self, x: int) -> bool:
        return x > self.above and (self.up_to is None or x <= self.up_to)

    def deduction(self, x: int) -> Fraction:
        if self.rate is None:
            return Fraction(self.base)
        return self.base + (x - self.above) * self.rate

    def parameter_names(self) -> tuple[str, ...]:
        base = f"{P_DEDUCTION}.{self.key}"
        if self.rate is None:
            return (f"{base}.超", f"{base}.額")
        return (f"{base}.超", f"{base}.以下", f"{base}.基礎", f"{base}.率.分子", f"{base}.率.分母")


@dataclass(frozen=True)
class LowBracket:
    """所得税法第28条第3項の収入360万円以下の第1の区分：x <= up_to で max(base + x × rate, minimum)。"""

    key: str
    up_to: int
    base: int
    rate: Fraction
    minimum: int

    def contains(self, x: int) -> bool:
        return x <= self.up_to

    def deduction(self, x: int) -> Fraction:
        return max(Fraction(self.base) + x * self.rate, Fraction(self.minimum))

    def parameter_names(self) -> tuple[str, ...]:
        base = f"{P_DEDUCTION}.{self.key}"
        return (f"{base}.以下", f"{base}.基礎", f"{base}.率.分子", f"{base}.率.分母", f"{base}.最低")


@dataclass(frozen=True)
class Sochi1:
    """措置法第29条の4第1項（令和8年・令和9年）：収入金額が upper 以下なら amount（収入金額が amount に満たなければ収入金額）。"""

    upper: int
    amount: int


@dataclass(frozen=True)
class KyuyoRules:
    table: Beppyo5Table
    table_upper: int
    sochi_applies: bool
    sochi: tuple[SochiBracket, ...]
    deduction: tuple[DeductionBracket, ...]


@dataclass(frozen=True)
class DeductionRules:
    """給与所得控除額の規定（所得税法第28条第3項、措置法第29条の4第1項）。別表第五は使わない。"""

    low: LowBracket
    mid: DeductionBracket
    brackets: tuple[DeductionBracket, ...]
    sochi1: Sochi1 | None


@dataclass(frozen=True)
class DeductionDetail:
    """所得税_給与所得控除額（有理数のまま）と、それを決めた規定のパラメータの名前（根拠）。"""

    amount: Fraction
    parameter_names: tuple[str, ...]


@dataclass(frozen=True)
class KyuyoDetail:
    """給与所得の金額と、それを決めた規定・使ったパラメータ・表の行・端数処理。"""

    income: int
    value: int
    path: KyuyoPath
    parameter_names: tuple[str, ...]
    table_row: Beppyo5Row | None = None
    sochi_bracket: SochiBracket | None = None
    deduction_bracket: DeductionBracket | None = None
    deduction: Fraction | None = None
    rounding: RoundingRule | None = None


def _int(v: Any, name: str) -> int:
    if type(v) is not int:
        raise TypeError(f"パラメータ {name} は整数が必要（{type(v).__name__}）")
    return v


def rules_from_parameters(p: Any) -> KyuyoRules:
    """parameters(期間)（OpenFisca の ParameterNodeAtInstant。追跡つきでもよい）から規則を作る。"""
    k = p.所得税.給与所得
    table_id = k.別表第五
    if not isinstance(table_id, str):
        raise TypeError(f"{P_TABLE} は表 ID の文字列が必要")
    table = load_beppyo5(table_id)
    table_upper = _int(k.別表第五を使う収入の上限, P_TABLE_UPPER)
    s = k.措法第29条の4第2項
    applies = s.適用
    if type(applies) is not bool:
        raise TypeError(f"{P_SOCHI_APPLIES} は真偽値が必要")
    sochi: tuple[SochiBracket, ...] = ()
    if applies:
        kinds = {1: "zero", 2: "minus", 3: "fixed", 4: "fixed", 5: "fixed"}
        brackets = []
        for n, kind in kinds.items():
            g = getattr(s, f"第{n}号")
            amount = g.控除額 if kind == "minus" else g.給与所得
            brackets.append(
                SochiBracket(
                    number=n,
                    lower=_int(g.以上, f"{P_SOCHI}.第{n}号.以上"),
                    upper=_int(g.未満, f"{P_SOCHI}.第{n}号.未満"),
                    kind=kind,
                    amount=_int(amount, f"{P_SOCHI}.第{n}号"),
                )
            )
        for prev, cur in zip(brackets, brackets[1:]):
            if prev.upper != cur.lower:
                raise ValueError("措置法第29条の4第2項の号の区分に隙間・重なりがある")
        sochi = tuple(brackets)
    return KyuyoRules(table, table_upper, applies, sochi, _brackets(p))


def _brackets(p: Any) -> tuple[DeductionBracket, ...]:
    d = p.所得税.給与所得控除額
    out = []
    for key in ("収入360万円超660万円以下", "収入660万円超850万円以下"):
        g = getattr(d, key)
        out.append(
            DeductionBracket(
                key=key,
                above=_int(g.超, f"{P_DEDUCTION}.{key}.超"),
                up_to=_int(g.以下, f"{P_DEDUCTION}.{key}.以下"),
                base=_int(g.基礎, f"{P_DEDUCTION}.{key}.基礎"),
                rate=Fraction(_int(g.率.分子, "率.分子"), _int(g.率.分母, "率.分母")),
            )
        )
    g = d.収入850万円超
    out.append(
        DeductionBracket(
            key="収入850万円超",
            above=_int(g.超, f"{P_DEDUCTION}.収入850万円超.超"),
            up_to=None,
            base=_int(g.額, f"{P_DEDUCTION}.収入850万円超.額"),
            rate=None,
        )
    )
    return tuple(out)


def deduction_rules_from_parameters(p: Any) -> DeductionRules:
    """parameters(期間) から給与所得控除額の規定を作る（別表第五は読まない）。"""
    d = p.所得税.給与所得控除額
    g = d.収入360万円以下の第1区分
    low = LowBracket(
        key="収入360万円以下の第1区分",
        up_to=_int(g.以下, f"{P_DEDUCTION}.収入360万円以下の第1区分.以下"),
        base=_int(g.基礎, f"{P_DEDUCTION}.収入360万円以下の第1区分.基礎"),
        rate=Fraction(_int(g.率.分子, "率.分子"), _int(g.率.分母, "率.分母")),
        minimum=_int(g.最低, f"{P_DEDUCTION}.収入360万円以下の第1区分.最低"),
    )
    g = d.収入360万円以下の第2区分
    mid = DeductionBracket(
        key="収入360万円以下の第2区分",
        above=_int(g.超, f"{P_DEDUCTION}.収入360万円以下の第2区分.超"),
        up_to=_int(g.以下, f"{P_DEDUCTION}.収入360万円以下の第2区分.以下"),
        base=_int(g.基礎, f"{P_DEDUCTION}.収入360万円以下の第2区分.基礎"),
        rate=Fraction(_int(g.率.分子, "率.分子"), _int(g.率.分母, "率.分母")),
    )
    s1 = p.所得税.給与所得.措法第29条の4第1項
    if type(s1.適用) is not bool:
        raise TypeError(f"{P_SOCHI1}.適用 は真偽値が必要")
    sochi1 = Sochi1(_int(s1.上限, f"{P_SOCHI1}.上限"), _int(s1.額, f"{P_SOCHI1}.額")) if s1.適用 else None
    return DeductionRules(low, mid, _brackets(p), sochi1)


def kyuyo_deduction(income: int, rules: DeductionRules) -> DeductionDetail:
    """所得税法第28条第3項（令和8年・9年は措置法第29条の4第1項）の給与所得控除額（有理数のまま）。

    別表第五や措置法第29条の4第2項で給与所得の金額を決める人でも、「第二十八条第二項に規定する給与所得控除額」はこの式で決まる
    （措法第27条が引く額。別表第五は「給与所得控除後の給与等の金額」を与えるだけで控除額を定めない：kyuyo-sources §1.1・§2.4）。
    """
    if type(income) is not int or income < 0:
        raise ValueError("給与等の収入金額は0以上の整数の円")
    if rules.sochi1 is not None and income <= rules.sochi1.upper:
        return DeductionDetail(Fraction(min(income, rules.sochi1.amount)), (f"{P_SOCHI1}.適用", f"{P_SOCHI1}.上限", f"{P_SOCHI1}.額"))
    if rules.low.contains(income):
        return DeductionDetail(rules.low.deduction(income), rules.low.parameter_names())
    if rules.mid.contains(income):
        return DeductionDetail(rules.mid.deduction(income), rules.mid.parameter_names())
    for b in rules.brackets:
        if b.contains(income):
            return DeductionDetail(b.deduction(income), b.parameter_names())
    raise ValueError(f"給与所得控除額の区分の外: {income}")


def kyuyo_shotoku(income: int, rules: KyuyoRules) -> KyuyoDetail:
    """その年中の給与等の収入金額（合計）から給与所得の金額を求める。"""
    if type(income) is not int or income < 0:
        raise ValueError("給与等の収入金額は0以上の整数の円")
    common = (P_SOCHI_APPLIES,)
    if rules.sochi_applies:
        common = common + (f"{P_SOCHI}.第1号.以上", f"{P_SOCHI}.第5号.未満")
        for b in rules.sochi:
            if b.contains(income):
                return KyuyoDetail(
                    income=income,
                    value=b.value(income),
                    path=KyuyoPath.SOCHI_29_4_2,
                    parameter_names=(P_SOCHI_APPLIES,) + b.parameter_names(),
                    sochi_bracket=b,
                )
    if income < rules.table_upper:
        row = rules.table.row_for(income)
        if row.kind == "fixed":
            value = row.value
        elif row.kind == "minus":
            value = income - row.c  # type: ignore[operator]
        else:  # 660万円未満に式の区分 rate_minus・1点の区分はない（tables の検査と tests で確かめる）
            raise ValueError(f"別表第五の660万円未満に想定しない区分: {row.kind}")
        assert value is not None and value >= 0
        return KyuyoDetail(
            income=income,
            value=value,
            path=KyuyoPath.BEPPYO5,
            parameter_names=common + (P_TABLE_UPPER, P_TABLE),
            table_row=row,
        )
    for b in rules.deduction:
        if b.contains(income):
            ded = b.deduction(income)
            value = KYUYO_SHOTOKU_660MAN_FLOOR.apply(income - ded)
            if value < 0:  # 660万円以上では起きない（控除額は最大195万円）
                raise ValueError(f"給与所得の金額が負になった: {income}")
            return KyuyoDetail(
                income=income,
                value=value,
                path=KyuyoPath.ART28_2_3,
                parameter_names=common + (P_TABLE_UPPER,) + b.parameter_names(),
                deduction_bracket=b,
                deduction=ded,
                rounding=KYUYO_SHOTOKU_660MAN_FLOOR,
            )
    raise ValueError(f"給与所得控除額の区分の外: {income}")

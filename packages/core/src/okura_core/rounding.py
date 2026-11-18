"""名前つきの端数処理（D13・D21 R5・D22 S3）。

規則：
  1. 途中の値は有理数（Fraction）で持ち、丸めは根拠のある箇所でだけ、この文書の名前つきの規則（RoundingRule）で行う。
  2. 根拠は「法令＞通達＞手引き＞国税庁の説明」の順で一番強いものに従う。法令以外なら根拠の種類でそれが分かる。
  3. 根拠がない端数は、候補（切捨て・切上げ・四捨五入）の全部で評価する（evaluate_unfounded）。
     金額だけが違えば幅（YenRange）で返し、判定が分かれたときだけ「未確定」にする（D22 S3）。
     既定の候補を黙って選ばない（D19・D21 R5）。

関数そのもの（floor_yen など）は数学の定義で、根拠を持たない。根拠は RoundingRule が持つ。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Generic, TypeVar

from .basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from .money import YenRange, to_fraction
from .candidates import Candidate, Merged, Policy, Slot, merge
from .result import Means, Undetermined

T = TypeVar("T")


def floor_yen(x: int | Fraction) -> int:
    """1円未満を切り捨てる（負の数は小さい方へ。数学の floor）。"""
    return math.floor(to_fraction(x))


def ceil_yen(x: int | Fraction) -> int:
    """1円未満を切り上げる（数学の ceil）。"""
    return math.ceil(to_fraction(x))


def half_up_yen(x: int | Fraction) -> int:
    """1円未満を四捨五入する（0.5 は大きい方へ。floor(x + 1/2)）。"""
    return math.floor(to_fraction(x) + Fraction(1, 2))


def floor_to_unit(x: int | Fraction, unit: int) -> int:
    """unit 円未満を切り捨てる（例：unit=1000 で千円未満切捨て）。"""
    if type(unit) is not int or unit <= 0:
        raise ValueError("単位は1以上の整数")
    return math.floor(to_fraction(x) / unit) * unit


#: 関数の名前 → 関数。RoundingRule.function と、根拠のないときの候補に使う。
FUNCTIONS: dict[str, Callable[[int | Fraction], int]] = {
    "floor": floor_yen,
    "ceil": ceil_yen,
    "half_up": half_up_yen,
}

#: 根拠のない1円未満の端数の候補（D21 R5・D22 S3）。名前 → 日本語の名前。
UNFOUNDED_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("floor", "切捨て"),
    ("ceil", "切上げ"),
    ("half_up", "四捨五入"),
)


@dataclass(frozen=True)
class RoundingRule:
    """根拠のある名前つきの端数処理。

    name は英語の関数名（結果の根拠に出る）。function は FUNCTIONS のキー。
    """

    name: str
    title: str
    function: str
    source_kind: SourceKind
    references: tuple[str, ...]
    law: str
    flags: tuple[ReadingFlag, ...] = ()

    def __post_init__(self) -> None:
        if self.function not in FUNCTIONS:
            raise ValueError(f"知らない端数処理の関数: {self.function}")
        if not self.references:
            raise ValueError(f"端数処理の出典がない: {self.name}")

    def apply(self, x: int | Fraction) -> int:
        return FUNCTIONS[self.function](x)

    def basis_entry(self) -> BasisEntry:
        return BasisEntry(
            type=BasisType.ROUNDING,
            name=self.name,
            source_kind=self.source_kind,
            references=self.references,
            flags=self.flags,
            law=self.law,
            detail={"function": self.function, "title": self.title},
        )


# ---------------------------------------------------------------------------
# 根拠のある端数処理（ここに足す。docstring 代わりに title・law・references を必ず書く）
# ---------------------------------------------------------------------------

KYUYO_SHOTOKU_660MAN_FLOOR = RoundingRule(
    name="floor_yen_kyuyo_shotoku_660man_or_more",
    title="給与等の収入金額が660万円以上のときの給与所得の金額の1円未満の端数を切り捨てる",
    function="floor",
    source_kind=SourceKind.LAW,
    law=(
        "所得税法 別表第五 備考（「給与等の金額が６，６００，０００円以上の居住者の給与所得控除後の給与等の金額に"
        "１円未満の端数があるときは、これを切り捨てた額」）。第28条第2項・第3項自体には端数の定めがなく、"
        "確定申告の給与所得への当てはめは読み"
    ),
    references=(
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#1.2",
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#6",
        "docs/measurements/20261109_impl-prep_kyuyo-thresholds.md#5",
        "docs/hypotheses/20261109_impl-prep_kyuyo-hypotheses.md#H6",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
)


# ---------------------------------------------------------------------------
# 根拠のない端数：候補の全部で評価する（候補の評価の道具 candidates.py と同じまとめ方）
# ---------------------------------------------------------------------------


def unfounded_slot(name: str, *, split_id: str | None = None, target: dict[str, object] | None = None) -> Slot:
    """根拠のない端数の分かれ目（候補：切捨て・切上げ・四捨五入、方針 ROUNDING、決める手段は一次情報）。

    規則モジュールが RoundingSlot として宣言するときも、evaluate_unfounded も、この形を使う。
    """
    if not name:
        raise ValueError("端数の名前が要る")
    return Slot(
        id=split_id or f"端数:{name}",
        means=Means.PRIMARY_SOURCE,
        target={"rounding": name, **(target or {})},
        candidates=tuple(Candidate(value=cand, label=cand) for cand, _ in UNFOUNDED_CANDIDATES),
        policy=Policy.ROUNDING,
    )


@dataclass(frozen=True)
class UnfoundedOutcome(Generic[T]):
    """根拠のない端数を候補の全部で評価した結果。values は (候補の名前, 値) の並び（候補の順）。"""

    name: str
    values: tuple[tuple[str, T], ...]

    @property
    def agree(self) -> bool:
        first = self.values[0][1]
        return all(v == first for _, v in self.values)

    def _merge(self, split_id: str, target: dict[str, object]) -> Merged:
        slot = unfounded_slot(self.name, split_id=split_id, target=target)
        by_label = {c.label: c for c in slot.candidates}
        return merge([slot], [({slot.id: by_label[c]}, v) for c, v in self.values])

    def as_amount(self) -> int | YenRange:
        """金額として：候補で同じなら整数、違えば幅（D22 S3。未確定にはしない）。"""
        for _, a in self.values:
            if type(a) is not int:
                raise TypeError("金額の候補は整数の円")
        m = self._merge(f"端数:{self.name}", {})
        assert m.undetermined is None
        return m.value  # type: ignore[no-any-return]

    def as_judgment(self, *, split_id: str, target: dict[str, object]) -> tuple[T | None, Undetermined | None]:
        """判定として：候補で同じなら (値, None)、分かれれば (None, 未確定の説明)（D22 S3）。"""
        if self.agree:
            return self.values[0][1], None
        m = self._merge(split_id, target)
        if m.undetermined is None:  # 判定の値は幅にしない
            raise TypeError("判定の候補に金額が来た（as_amount を使う）")
        return None, m.undetermined

    def basis_entry(self) -> BasisEntry:
        """「根拠なし（候補で評価）」の根拠の項目。"""
        return BasisEntry(
            type=BasisType.ROUNDING,
            name=self.name,
            source_kind=None,
            references=(),
            detail={
                "title": "根拠なし（候補で評価）",
                "candidates": {c: v for c, v in self.values},
            },
        )


def evaluate_unfounded(name: str, compute: Callable[[Callable[[int | Fraction], int]], T]) -> UnfoundedOutcome[T]:
    """根拠のない端数を候補（切捨て・切上げ・四捨五入）の全部で評価する。

    compute は「丸めの関数」を受け取って値（金額・判定）を返す純粋関数。候補ごとに1回ずつ呼ぶ。
    OpenFisca の式の中の端数は、規則モジュールが RoundingSlot を宣言し、evaluate が候補ごとに評価する（registry.py）。
    """
    if not name:
        raise ValueError("端数の名前が要る")
    values = tuple((cand, compute(FUNCTIONS[cand])) for cand, _ in UNFOUNDED_CANDIDATES)
    return UnfoundedOutcome(name=name, values=values)

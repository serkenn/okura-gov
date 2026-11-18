"""候補の評価（D21 R5・R6、D22 S3・S20）：決まらない入力を候補の全部で評価し、結論をまとめる道具。

決まらない入力（分かれ目）には2つの種類があり、同じ道具で扱う：

- 判断・選択の未入力（D21 R6、D22 S20）：ありうる値（中間表現の語彙の値の領域）の全部で評価する。
  結論が同じなら断定、違えば「未確定」と「何を入力すれば決まるか」（分かれ目）を返す。金額が違っても未確定。
  方針 JUDGMENT。
- 根拠のない端数（D21 R5・D22 S3）：候補（切捨て・切上げ・四捨五入）の全部で評価する。
  金額だけが違えば幅（YenRange）で返し、判定（真偽・区分・整数）が分かれたときだけ未確定。方針 ROUNDING。
  判断・選択と両方が金額を変えるときは、判断・選択の分かれ目だけで未確定にし、候補ごとの値を端数の幅にする（merge の説明）。
- 法令の読みの候補（D22 S1・S3。2026-11-12）：一次情報で決まらない読み（支えが同程度の2つ以上の読み）。端数と同じく、
  金額だけが違えば幅、判定が分かれたときだけ未確定（決める手段は一次情報）。方針 READING。
- 単調な判断の両端評価（D21 R6）：支出ごとに分かれ目があって直積が爆発する判断で、モジュールが値の単調さを宣言したもの。
  両端（全部 候補0・全部 候補1）だけで評価する。結論が同じなら断定、金額が違えば幅、判定が分かれたら未確定。方針 MONOTONE。

組合せ：分かれ目が複数あれば候補の直積を評価する。直積の数が上限（MAX_ASSIGNMENTS）を超えたら評価せず、
呼び出し側が「候補が多すぎる」として未確定で返す（TooManyCandidates）。上限は評価の時間を抑えるための仮の値で、法令の値ではない。

純粋関数だけ（状態を持たない）。値の比較は == で行う（金額は整数の円、判定は bool など）。
"""

from __future__ import annotations

import enum
import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .money import YenRange
from .result import CandidateOutcome, Means, Split, Undetermined

#: 1つのシナリオ・年分で評価する候補の組合せの上限（直積の数）。超えたら評価しない（未確定で返す）。
MAX_ASSIGNMENTS = 64


class Policy(enum.Enum):
    """結論のまとめ方。"""

    #: 判断・選択：値が1つでも違えば未確定（金額も）。
    JUDGMENT = "judgment"
    #: 根拠のない端数：金額だけが違えば幅、判定が違えば未確定。
    ROUNDING = "rounding"
    #: 単調な判断の両端評価：両端の金額が違えば幅、判定が違えば未確定（金額のまとめ方は ROUNDING と同じ）。
    MONOTONE = "monotone"
    #: 法令の読みの候補：金額だけが違えば幅、判定が違えば未確定（まとめ方は ROUNDING と同じ。D22 S3 を読みにも当てる）。
    READING = "reading"


@dataclass(frozen=True)
class Candidate:
    """分かれ目の候補。value は規則に渡す値、label は結果に出す名前（文字列）。"""

    value: Any
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("候補の名前は空でない文字列")


@dataclass(frozen=True)
class Slot:
    """分かれ目。id は結果の Split.id、target は何についての分かれ目か（人・記録の種類・年分など）。

    persons は関係する人（人のつながりの計算に使う）。空なら全部の人のつながりに入る（根拠のない端数など）。
    """

    id: str
    means: Means
    target: Mapping[str, Any]
    candidates: tuple[Candidate, ...]
    policy: Policy = Policy.JUDGMENT
    persons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("分かれ目の ID が空")
        if len(self.candidates) < 1:
            raise ValueError(f"分かれ目 {self.id} に候補がない")
        labels = [c.label for c in self.candidates]
        if len(set(labels)) != len(labels):
            raise ValueError(f"分かれ目 {self.id} の候補の名前が重複している")

    def split(self, splits_conclusion: bool) -> Split:
        return Split(
            id=self.id,
            means=self.means,
            target=dict(self.target),
            candidates=tuple(c.label for c in self.candidates),
            splits_conclusion=splits_conclusion,
        )


class TooManyCandidates(Exception):
    """候補の組合せが上限を超えた。count は直積の数。"""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(f"候補の組合せが {count} 通りで、上限 {limit} を超える")


Assignment = Mapping[str, Candidate]


def count_assignments(slots: Sequence[Slot]) -> int:
    n = 1
    for s in slots:
        n *= len(s.candidates)
    return n


def assignments(slots: Sequence[Slot], limit: int = MAX_ASSIGNMENTS) -> list[dict[str, Candidate]]:
    """分かれ目の候補の直積（分かれ目の並びの順、候補の順）。分かれ目がなければ空の組1つ。上限を超えたら TooManyCandidates。"""
    ids = [s.id for s in slots]
    if len(set(ids)) != len(ids):
        raise ValueError("分かれ目の ID が重複している")
    n = count_assignments(slots)
    if n > limit:
        raise TooManyCandidates(n, limit)
    return [dict(zip(ids, combo)) for combo in itertools.product(*(s.candidates for s in slots))]


@dataclass(frozen=True)
class Merged:
    """候補ごとの値をまとめた結果。

    - value：結論（全部の候補で同じ値、又は金額の幅）。未確定なら None。
    - undetermined：未確定のときの分かれ目と候補ごとの値。
    - evaluated：評価した分かれ目（結論を分けたかつき）。確定したときも残す（design-output §5.1 の 3）。
    """

    value: Any
    undetermined: Undetermined | None
    evaluated: tuple[Split, ...] = field(default=())


def _labels(a: Assignment) -> dict[str, str]:
    return {k: c.label for k, c in a.items()}


def _decisive(slots: Sequence[Slot], runs: Sequence[tuple[Assignment, Any]]) -> list[Slot]:
    """値を変える分かれ目：ほかの分かれ目の候補が同じで、その分かれ目の候補だけが違う2つの評価で値が違うもの。"""
    out: list[Slot] = []
    for s in slots:
        others = [x.id for x in slots if x.id != s.id]
        groups: dict[tuple[str, ...], list[Any]] = {}
        for a, v in runs:
            groups.setdefault(tuple(a[o].label for o in others), []).append(v)
        if any(any(v != vs[0] for v in vs[1:]) for vs in groups.values()):
            out.append(s)
    return out


#: 金額の違いを幅にする方針（判断・選択の JUDGMENT では金額も未確定）。
_RANGE_POLICIES = frozenset({Policy.ROUNDING, Policy.MONOTONE, Policy.READING})


def _is_amount(v: Any) -> bool:
    return type(v) is int


def merge(slots: Sequence[Slot], runs: Sequence[tuple[Assignment, Any]], *, amount: bool | None = None) -> Merged:
    """候補ごとの値（runs：候補の組と値）を、分かれ目の方針でまとめる。runs は assignments(slots) の全部であること。

    amount：値が金額（円）か。None なら値の型（int で bool でない）で決める。整数（人数など）・判定は金額でないので、
    根拠のない端数で分かれても幅にせず未確定にする（D22 S3「判定が分かれたときだけ未確定」の判定の側）。
    判断・選択と根拠のない端数の両方が値を変えるときは、判断・選択の分かれ目だけで未確定にし、候補の組ごとの値を
    端数の候補の幅で返す（端数は何を入力しても決まらないので「何を入力すれば決まるか」に入れない）。
    """
    if not runs:
        raise ValueError("評価の結果がない")
    if len(runs) != count_assignments(slots):
        raise ValueError("候補の組合せの全部を評価していない")
    values = [v for _, v in runs]
    if all(v == values[0] for v in values[1:]):
        return Merged(values[0], None, tuple(s.split(False) for s in slots))
    decisive = _decisive(slots, runs)
    if not decisive:  # 値が違うのに、どの分かれ目も単独では変えない（組合せでだけ変わる）：全部を結論を分けるものとする
        decisive = list(slots)
    decisive_ids = {s.id for s in decisive}
    evaluated = tuple(s.split(s.id in decisive_ids) for s in slots)
    is_amount = all(_is_amount(v) for v in values) and (amount is None or amount)
    deciding = [s for s in decisive if not (is_amount and s.policy in _RANGE_POLICIES)]
    if not deciding:
        return Merged(YenRange.of(values), None, evaluated)
    deciding_ids = {s.id for s in deciding}
    grouped: dict[tuple[tuple[str, str], ...], list[Any]] = {}
    for a, v in runs:
        key = tuple(sorted((k, c.label) for k, c in a.items() if k in deciding_ids))
        grouped.setdefault(key, []).append(v)

    def one(vs: list[Any]) -> Any:
        if all(v == vs[0] for v in vs[1:]) or not is_amount:
            return vs[0]
        return YenRange.of(vs)  # 判断の候補の中で、端数の候補だけで違う金額

    outcomes = tuple(CandidateOutcome(conditions=dict(k), value=one(vs)) for k, vs in grouped.items())
    und = Undetermined(splits=tuple(s.split(True) for s in deciding), outcomes=outcomes)
    return Merged(None, und, evaluated)


def labels_of(a: Assignment) -> dict[str, str]:
    """候補の組の名前（分かれ目の ID → 候補の名前）。"""
    return _labels(a)


__all__ = [
    "MAX_ASSIGNMENTS",
    "Assignment",
    "Candidate",
    "Merged",
    "Policy",
    "Slot",
    "TooManyCandidates",
    "assignments",
    "count_assignments",
    "labels_of",
    "merge",
]

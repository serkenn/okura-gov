"""判定コアの結果のモデル（D22 S2・S3、D19、D21 R2・R6、SCOPE §8）と JSON への直列化。

- 値（ResultValue）：概念 ID × 人 × 時点 ごとに1つ。値は金額（整数の円）・金額の幅・真偽・整数・区分・日付・なし。
- 状態（State）：後続の処理を変えるもの。見積り・計画・予測・未確定・対象外。値ごとに集合で持つ。
- 根拠（basis.BasisEntry）：値ごとの出典と根拠の種類（状態とは別の項目。D22 S2）。
- 境目の説明（Boundary）：使った基準、今の値、差、境目の種類（SCOPE §2-6）。
- 未確定（Undetermined）：何を入力・注入すれば決まるか（分かれ目と候補ごとの結論。D21 R6）。
- 申告用の値（FilingEntry）：予測・未確定・対象外を含む申告者・年分からは出さない（D19・D21 R2）。
  この規則は build_filing でだけ作れる形にして、この層で強制する。

JSON のキーは英語、状態・根拠の種類などの値は日本語（中間表現の mark と同じ語）。
"""

from __future__ import annotations

import datetime as _dt
import enum
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .basis import BasisEntry
from .money import YenRange

RESULT_SCHEMA_VERSION = "2"  # 1：根拠を一覧（basis）に1回だけ置き、値・境目・欄からは番号で引く。シナリオの差・欄の値を足した（2026-11-12）。2：年齢の境目（age_boundaries）を足した（2026-11-12）


class State(enum.Enum):
    """結果の状態（D22 S2）。"""

    ESTIMATE = "見積り"  # 法令が求める見積り（申告用の値を出す・印つき。D21 R2）
    PLAN = "計画"  # 申告の計画（条件つきで出す。D21 R2）
    FORECAST = "予測"  # 見込み（申告用の値を出さない。D19・D21 R2）
    UNDETERMINED = "未確定"
    OUT_OF_SCOPE = "対象外"

    @classmethod
    def from_mark(cls, mark: str) -> State:
        """中間表現の mark（見積り・計画・予測）を状態にする。"""
        for s in (cls.ESTIMATE, cls.PLAN, cls.FORECAST):
            if s.value == mark:
                return s
        raise ValueError(f"中間表現の印として知らない値: {mark!r}")


#: 状態を出力するときの順序（決定的な出力のため）。
STATE_ORDER: tuple[State, ...] = (
    State.OUT_OF_SCOPE,
    State.UNDETERMINED,
    State.FORECAST,
    State.ESTIMATE,
    State.PLAN,
)

#: 申告用の値を止める状態（D19・D21 R2）。見積り・計画では止めない。
FILING_BLOCKING_STATES: frozenset[State] = frozenset({State.FORECAST, State.UNDETERMINED, State.OUT_OF_SCOPE})

#: 依存する値へ伝える状態（design-output §1.4）。対象外・未確定も伝える。
PROPAGATING_STATES: frozenset[State] = frozenset(State)


def ordered_states(states: Iterable[State]) -> list[State]:
    s = set(states)
    return [x for x in STATE_ORDER if x in s]


class OutOfScopeCategory(enum.Enum):
    """対象外の区分（design-output §1.2）。"""

    OUT_OF_RANGE = "範囲外"  # 責務の外（D20・SCOPE §4）
    OUT_OF_YEARS = "年分外"  # 対象の年分・年度の外（SCOPE §5）
    NOT_IMPLEMENTED = "未対応"  # 範囲の中だが、この版では実装していない


class Means(enum.Enum):
    """未確定を決める手段（design-output §5.3）。"""

    INJECTION = "注入"
    JUDGMENT = "判断"
    FACT = "事実"
    PRIMARY_SOURCE = "一次情報"
    AWAITING_PUBLICATION = "公表待ち"


class Comparison(enum.Enum):
    """境目の比較の向き。「量 比較 基準」が成り立てば要件を満たす。"""

    AT_MOST = "以下"
    LESS_THAN = "未満"
    MORE_THAN = "超"
    AT_LEAST = "以上"

    @classmethod
    def from_label(cls, label: str) -> Comparison:
        for c in cls:
            if c.value == label:
                return c
        raise ValueError(f"比較の向きとして知らない名前: {label!r}")

    def holds(self, quantity: int, criterion: int) -> bool:
        if self is Comparison.AT_MOST:
            return quantity <= criterion
        if self is Comparison.LESS_THAN:
            return quantity < criterion
        if self is Comparison.MORE_THAN:
            return quantity > criterion
        return quantity >= criterion

    def crossing_value(self, quantity: int, criterion: int) -> int:
        """境目の向こう側の最初の値（整数の円）。今の結論が変わる、今の値に一番近い値。"""
        satisfied = self.holds(quantity, criterion)
        if self is Comparison.AT_MOST:
            return criterion + 1 if satisfied else criterion
        if self is Comparison.LESS_THAN:
            return criterion if satisfied else criterion - 1
        if self is Comparison.MORE_THAN:
            return criterion if satisfied else criterion + 1
        return criterion - 1 if satisfied else criterion

    @property
    def boundary_kind(self) -> str:
        """境目の種類：上限（以下・未満）か下限（超・以上）か。"""
        return "上限" if self in (Comparison.AT_MOST, Comparison.LESS_THAN) else "下限"


# ---------------------------------------------------------------------------
# 値
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YenAmount:
    amount: int

    def __post_init__(self) -> None:
        if type(self.amount) is not int:
            raise TypeError("金額は整数の円")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "yen", "amount": self.amount}


@dataclass(frozen=True)
class Flag:
    value: bool

    def __post_init__(self) -> None:
        if type(self.value) is not bool:
            raise TypeError("真偽の値は bool")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "bool", "value": self.value}


@dataclass(frozen=True)
class Count:
    """整数（年齢・人数など。金額ではない）。"""

    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int:
            raise TypeError("整数の値は int")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "integer", "value": self.value}


@dataclass(frozen=True)
class Category:
    """区分（列挙の値の名前）。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise TypeError("区分の値は空でない文字列")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "category", "value": self.value}


@dataclass(frozen=True)
class DateValue:
    """日付（申告期限など）。"""

    on: _dt.date

    def __post_init__(self) -> None:
        if type(self.on) is not _dt.date:
            raise TypeError("日付の値は datetime.date")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "date", "on": self.on.isoformat()}


Value = YenAmount | YenRange | Flag | Count | Category | DateValue
VALUE_CLASSES: tuple[type, ...] = (YenAmount, YenRange, Flag, Count, Category, DateValue)


def _value_to_json(v: Any) -> Any:
    if v is None or type(v) in (bool, int, str):
        return v
    if isinstance(v, VALUE_CLASSES):
        return v.to_dict()
    raise TypeError(f"JSON にできない値: {type(v).__name__}")


BasisRef = Callable[[BasisEntry], int]


class BasisTable:
    """根拠の一覧（結果の JSON の basis）。同じ根拠の項目は1回だけ置き、値・境目・欄からは番号で引く（JSON の大きさを抑える）。

    番号は最初に引いた順（結果の値の並びは決定的なので、番号も決定的）。同じ内容の項目は、別のオブジェクトでも同じ番号。
    """

    def __init__(self) -> None:
        self._by_id: dict[int, int] = {}
        self._by_key: dict[str, int] = {}
        self._entries: list[BasisEntry] = []
        self._dicts: list[dict[str, Any]] = []

    def ref(self, entry: BasisEntry) -> int:
        i = self._by_id.get(id(entry))
        if i is not None:
            return i
        d = entry.to_dict()
        key = json.dumps(d, ensure_ascii=False, sort_keys=True)
        i = self._by_key.get(key)
        if i is None:
            i = self._by_key[key] = len(self._dicts)
            self._dicts.append(d)
        self._entries.append(entry)  # id を使い回されないように持っておく
        self._by_id[id(entry)] = i
        return i

    def to_list(self) -> list[dict[str, Any]]:
        return list(self._dicts)


def _basis_json(entry: BasisEntry, ref: BasisRef | None) -> Any:
    return entry.to_dict() if ref is None else ref(entry)


@dataclass(frozen=True)
class TimeKey:
    """時点：所得税の年分（tax_year）・年度（fiscal_year）・判定日（on）。"""

    kind: str
    value: int | str

    def __post_init__(self) -> None:
        if self.kind not in ("tax_year", "fiscal_year", "on"):
            raise ValueError(f"時点の種類として知らない名前: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        return {self.kind: self.value}


# ---------------------------------------------------------------------------
# 未確定
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    """分かれ目：決める手段・対象・候補・結論を分けるか。"""

    id: str
    means: Means
    target: Mapping[str, Any]
    candidates: tuple[str, ...]
    splits_conclusion: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "means": self.means.value,
            "target": dict(self.target),
            "candidates": list(self.candidates),
            "splits_conclusion": self.splits_conclusion,
        }


@dataclass(frozen=True)
class CandidateOutcome:
    """候補の組（分かれ目の ID → 候補）ごとの値。"""

    conditions: Mapping[str, str]
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"conditions": dict(self.conditions), "value": _value_to_json(self.value)}


@dataclass(frozen=True)
class Undetermined:
    """未確定のときに「何を入力・注入すれば決まるか」。"""

    splits: tuple[Split, ...]
    outcomes: tuple[CandidateOutcome, ...]

    def __post_init__(self) -> None:
        if not self.splits:
            raise ValueError("未確定には分かれ目が1つ以上要る")

    def to_dict(self) -> dict[str, Any]:
        return {"splits": [s.to_dict() for s in self.splits], "outcomes": [o.to_dict() for o in self.outcomes]}


# ---------------------------------------------------------------------------
# 結果の値
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutOfScopeReason:
    category: OutOfScopeCategory
    reason: str
    record_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category.value, "reason": self.reason, "record_ids": list(self.record_ids)}


@dataclass(frozen=True)
class ResultValue:
    """概念 ID × 人 × 時点 の値。

    - filing_item：申告書の欄に写す値か（様式の欄の対応表が使う）。
    - filing_scope：その人・年分の申告書の値の全体に効くか（申告用の値を止める判定に使う。
      filing_item の値と、集約点の概念〔合計所得金額など〕）。
    - evaluated：候補の全部で評価した分かれ目（D21 R6・D22 S3。結論が同じで確定した場合も残す。design-output §5.1 の 3）。
    """

    id: str
    concept: str
    variable: str | None
    person: str | None
    time: TimeKey
    value: Value | None
    states: frozenset[State]
    basis: tuple[BasisEntry, ...]
    depends_on: tuple[str, ...] = ()
    facts: tuple[str, ...] = ()
    undetermined: Undetermined | None = None
    out_of_scope: OutOfScopeReason | None = None
    filing_item: bool = False
    filing_scope: bool = False
    evaluated: tuple[Split, ...] = ()

    def __post_init__(self) -> None:
        if State.OUT_OF_SCOPE in self.states:
            if self.value is not None or self.out_of_scope is None:
                raise ValueError(f"{self.id}: 対象外の値は値を持たず理由を持つ")
        elif self.out_of_scope is not None:
            raise ValueError(f"{self.id}: 対象外の理由があるのに状態が対象外でない")
        if State.UNDETERMINED in self.states:
            if self.undetermined is None and State.OUT_OF_SCOPE not in self.states:
                raise ValueError(f"{self.id}: 未確定には分かれ目の説明が要る")
            if self.value is not None and not isinstance(self.value, YenRange):
                raise ValueError(f"{self.id}: 未確定の値はなしか幅")
        elif self.undetermined is not None:
            raise ValueError(f"{self.id}: 分かれ目の説明があるのに状態が未確定でない")
        if self.value is None and not (self.states & {State.OUT_OF_SCOPE, State.UNDETERMINED}):
            raise ValueError(f"{self.id}: 値がないのは未確定か対象外のときだけ")
        if self.filing_item and not self.filing_scope:
            raise ValueError(f"{self.id}: 申告書の欄に写す値は申告の範囲（filing_scope）に入る")

    def to_dict(self, ref: BasisRef | None = None) -> dict[str, Any]:
        """JSON にできる形。ref を渡すと根拠は一覧の番号（BasisTable.ref）、渡さなければ根拠の項目をそのまま書く。"""
        return {
            "id": self.id,
            "concept": self.concept,
            "variable": self.variable,
            "person": self.person,
            "time": self.time.to_dict(),
            "value": _value_to_json(self.value),
            "states": [s.value for s in ordered_states(self.states)],
            "basis": [_basis_json(b, ref) for b in self.basis],
            "depends_on": list(self.depends_on),
            "facts": list(self.facts),
            "undetermined": None if self.undetermined is None else self.undetermined.to_dict(),
            "out_of_scope": None if self.out_of_scope is None else self.out_of_scope.to_dict(),
            "filing_item": self.filing_item,
            "evaluated": [s.to_dict() for s in self.evaluated],
        }


@dataclass(frozen=True)
class OutOfScopeItem:
    """入力・問いの項目で、この版が扱わないもの（対象外。理由つき）。"""

    target: Mapping[str, Any]
    persons: tuple[str, ...]
    category: OutOfScopeCategory
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": dict(self.target),
            "persons": list(self.persons),
            "category": self.category.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Boundary:
    """境目の説明（SCOPE §2-6・§8、design-output §3）。

    比べる量（compared_value_id の値）と基準（criterion）を comparison で比べた判定（judgment_value_id）について、
    今の値・またぐ値（向こう側の最初の値）・差（またぐ値 − 今の値）と境目の種類（上限・下限）を出す。
    """

    id: str
    concept: str
    person: str
    time: TimeKey
    judgment_value_id: str
    judgment: bool
    compared_value_id: str
    compared_concept: str
    current: int
    criterion: BasisEntry
    criterion_value: int
    comparison: Comparison
    crossing_value: int
    difference: int
    states: frozenset[State]

    def __post_init__(self) -> None:
        if self.comparison.holds(self.current, self.criterion_value) != self.judgment:
            raise ValueError(f"{self.id}: 判定と比較の結果が食い違う")
        if self.comparison.crossing_value(self.current, self.criterion_value) != self.crossing_value:
            raise ValueError(f"{self.id}: またぐ値が比較の向きと合わない")
        if self.difference != self.crossing_value - self.current:
            raise ValueError(f"{self.id}: 差はまたぐ値 − 今の値")

    def to_dict(self, ref: BasisRef | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "concept": self.concept,
            "person": self.person,
            "time": self.time.to_dict(),
            "judgment": {"value_id": self.judgment_value_id, "value": self.judgment},
            "compared": {
                "value_id": self.compared_value_id,
                "concept": self.compared_concept,
                "current": self.current,
            },
            "criterion": {
                "value": self.criterion_value,
                "comparison": self.comparison.value,
                "basis": _basis_json(self.criterion, ref),
            },
            "kind": self.comparison.boundary_kind,
            "crossing_value": self.crossing_value,
            "difference": self.difference,
            "states": [s.value for s in ordered_states(self.states)],
        }


def attained_on(birth: _dt.date, age: int) -> _dt.date:
    """生年月日 birth の人が年齢 age に達する日（その日の終了時に達する。年齢計算ニ関スル法律・民法第143条）。

    age 年後の誕生日に応当する日の前日。応当する日がない（2月29日生まれで平年）ときは、その月の末日（2月28日）。
    """
    year = birth.year + age
    try:
        anniversary = _dt.date(year, birth.month, birth.day)
    except ValueError:  # 2月29日生まれの平年：応当する日がないので月の末日に満了（民法第143条第2項ただし書）
        anniversary = _dt.date(year, 3, 1)
    return anniversary - _dt.timedelta(days=1)


def age_at_end_of(birth: _dt.date, day: _dt.date) -> int:
    """day の終了時の年齢（attained_on と同じ数え方。day の翌日の暦の上の満年齢）。"""
    nxt = day + _dt.timedelta(days=1)
    return nxt.year - birth.year - ((nxt.month, nxt.day) < (birth.month, birth.day))


@dataclass(frozen=True)
class AgeBoundary:
    """年齢の境目の説明（2026-11-12。概念辞書の「年齢の境目」）：判定の日の終了時の年齢と基準の年齢の比較。

    例「その年12月31日に19歳以上か」：生年月日・判定の日・今の年齢・基準（年齢・比較・根拠）・比較の結果（holds）、
    結論が変わる年齢（crossing_age）、その年齢 threshold（以上・未満なら基準の年齢、以下・超なら基準＋1）に達する日（boundary_on）と、
    判定の日からその日までの日数（days_to_boundary。正ならまだ達していない：判定の日がその日数だけ後なら達する。0以下なら達している）。
    related は宣言した概念の値（年齢の比較を使う判定・基準額など）。年齢の比較だけを説明し、その比較が判定に効くかは related の値で見る。
    """

    id: str
    concept: str
    person: str
    time: TimeKey
    related_value_id: str
    related_concept: str
    age_value_id: str
    age_concept: str
    age: int
    birth_on: _dt.date
    reference_on: _dt.date
    reference: str
    criterion: BasisEntry
    criterion_value: int
    comparison: Comparison
    holds: bool
    crossing_age: int
    boundary_on: _dt.date
    days_to_boundary: int
    states: frozenset[State]

    def __post_init__(self) -> None:
        if age_at_end_of(self.birth_on, self.reference_on) != self.age:
            raise ValueError(f"{self.id}: 年齢が生年月日と判定の日から求めた年齢と違う")
        if self.comparison.holds(self.age, self.criterion_value) != self.holds:
            raise ValueError(f"{self.id}: 比較の結果が食い違う")
        if self.comparison.crossing_value(self.age, self.criterion_value) != self.crossing_age:
            raise ValueError(f"{self.id}: 結論が変わる年齢が比較の向きと合わない")
        threshold = self.criterion_value + (1 if self.comparison in (Comparison.AT_MOST, Comparison.MORE_THAN) else 0)
        if self.boundary_on != attained_on(self.birth_on, threshold):
            raise ValueError(f"{self.id}: 境目の日が基準の年齢に達する日でない")
        if self.days_to_boundary != (self.boundary_on - self.reference_on).days:
            raise ValueError(f"{self.id}: 日数は境目の日 − 判定の日")

    def to_dict(self, ref: BasisRef | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "concept": self.concept,
            "person": self.person,
            "time": self.time.to_dict(),
            "related": {"value_id": self.related_value_id, "concept": self.related_concept},
            "age": {
                "value_id": self.age_value_id,
                "concept": self.age_concept,
                "current": self.age,
                "birth_on": self.birth_on.isoformat(),
                "reference_on": self.reference_on.isoformat(),
                "reference": self.reference,
            },
            "criterion": {
                "value": self.criterion_value,
                "comparison": self.comparison.value,
                "basis": _basis_json(self.criterion, ref),
            },
            "holds": self.holds,
            "kind": self.comparison.boundary_kind,
            "crossing_age": self.crossing_age,
            "boundary_on": self.boundary_on.isoformat(),
            "days_to_boundary": self.days_to_boundary,
            "states": [s.value for s in ordered_states(self.states)],
        }


# ---------------------------------------------------------------------------
# 申告用の値（D19・D21 R2 の強制）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilingEntry:
    """申告用の値。build_filing だけが作る（予測・未確定・対象外を含む申告者・年分の値は作れない）。"""

    value_id: str
    concept: str
    person: str
    time: TimeKey
    amount: int
    states: frozenset[State]
    _token: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._token is not _FILING_TOKEN:
            raise PermissionError("申告用の値は build_filing でだけ作れる")
        if self.states & FILING_BLOCKING_STATES:
            raise ValueError(f"{self.value_id}: 予測・未確定・対象外の値は申告用の値にできない")
        if type(self.amount) is not int:
            raise TypeError("申告用の値は整数の円")

    def to_dict(self) -> dict[str, Any]:
        conditions = []
        if State.PLAN in self.states:
            conditions.append("申告の計画どおりに申告すること（計画）")
        if State.ESTIMATE in self.states:
            conditions.append("法令が求める見積りによる値（見積り）")
        return {
            "value_id": self.value_id,
            "concept": self.concept,
            "person": self.person,
            "time": self.time.to_dict(),
            "amount": self.amount,
            "states": [s.value for s in ordered_states(self.states)],
            "conditions": conditions,
        }


_FILING_TOKEN = object()


@dataclass(frozen=True)
class Withheld:
    """出さなかった申告用の値と理由。"""

    value_id: str
    concept: str
    person: str
    time: TimeKey
    reasons: tuple[str, ...]
    blocking_value_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_id": self.value_id,
            "concept": self.concept,
            "person": self.person,
            "time": self.time.to_dict(),
            "reasons": list(self.reasons),
            "blocking_value_ids": list(self.blocking_value_ids),
        }


def _basis_closure(values: Mapping[str, ResultValue], start: str) -> list[BasisEntry]:
    seen: set[str] = set()
    stack = [start]
    out: list[BasisEntry] = []
    while stack:
        vid = stack.pop()
        if vid in seen or vid not in values:
            continue
        seen.add(vid)
        out.extend(values[vid].basis)
        stack.extend(values[vid].depends_on)
    return out


def _late(by_id: Mapping[str, ResultValue], vid: str, filing_date: _dt.date) -> list[str]:
    """値（と依存した値）の根拠の施行日のうち、提出日より後のもの（重ねない・並べる）。"""
    return sorted({b.enforced_on for b in _basis_closure(by_id, vid) if b.enforced_on and b.enforced_on > filing_date.isoformat()})


def enforcement_after(
    person_year: Iterable[ResultValue], values: Iterable[ResultValue], filing_date: _dt.date | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """申告者・年分の申告の範囲の値（filing_scope）が依存した規定の施行日のうち、提出日より後のものと、その値の ID。

    build_filing の「施行日前の提出」と同じ判定（様式の欄の値〔forms_output〕も同じ関数で止める）。提出日がなければ空。
    """
    if filing_date is None:
        return (), ()
    by_id = {v.id: v for v in values}
    late: set[str] = set()
    blocking: list[str] = []
    for v in person_year:
        if not v.filing_scope:
            continue
        hit = _late(by_id, v.id, filing_date)
        if hit:
            late.update(hit)
            blocking.append(v.id)
    return tuple(sorted(late)), tuple(sorted(blocking))


def build_filing(
    values: Iterable[ResultValue], *, filing_date: _dt.date | None = None
) -> tuple[tuple[FilingEntry, ...], tuple[Withheld, ...]]:
    """申告用の値を作る。申告者・年分（人 × 時点）ごとに、申告の範囲の値に止める状態が1つでもあれば全部を止める。

    止める理由：
      - 予測・未確定・対象外（D19・D21 R2、design-output §1.2 の「申告者・年分の欄値表全体を止める」）
      - 幅（根拠のない端数で金額が1つに決まらない。欄に書けない）
      - 施行日前の提出（問いの提出日が、使った規定の施行日より前。施行前に出す申告書の値はこの版では出さない）
    """
    items = list(values)
    by_id = {v.id: v for v in items}
    groups: dict[tuple[str | None, str], list[ResultValue]] = {}
    for v in items:
        if v.filing_scope:
            groups.setdefault((v.person, json.dumps(v.time.to_dict(), sort_keys=True)), []).append(v)
    entries: list[FilingEntry] = []
    withheld: list[Withheld] = []
    for key in sorted(groups, key=lambda k: (k[0] or "", k[1])):
        group = groups[key]
        reasons: list[str] = []
        blocking: list[str] = []
        for v in group:
            hit = [s.value for s in ordered_states(v.states & FILING_BLOCKING_STATES)]
            if v.filing_item and isinstance(v.value, YenRange) and State.UNDETERMINED not in v.states:
                hit.append("幅")
            if filing_date is not None:
                late = _late(by_id, v.id, filing_date)
                if late:
                    hit.append("施行日前の提出（施行日 " + "・".join(late) + "）")
            if hit:
                blocking.append(v.id)
                for h in hit:
                    if h not in reasons:
                        reasons.append(h)
        for v in sorted(group, key=lambda x: x.id):
            if not v.filing_item:
                continue
            if reasons:
                withheld.append(
                    Withheld(
                        value_id=v.id,
                        concept=v.concept,
                        person=v.person or "",
                        time=v.time,
                        reasons=tuple(reasons),
                        blocking_value_ids=tuple(sorted(blocking)),
                    )
                )
            else:
                assert isinstance(v.value, YenAmount)
                entries.append(
                    FilingEntry(
                        value_id=v.id,
                        concept=v.concept,
                        person=v.person or "",
                        time=v.time,
                        amount=v.value.amount,
                        states=v.states,
                        _token=_FILING_TOKEN,
                    )
                )
    return tuple(entries), tuple(withheld)


# ---------------------------------------------------------------------------
# シナリオと全体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueDifference:
    """シナリオの値と、差分なしのシナリオ（base）の値の機械的な差（D19 の一括評価。比べて選ぶのは利用アプリ）。

    fields：違う項目（value・states・undetermined・out_of_scope）。片方にしかない値は fields が ("present",)。
    """

    value_id: str
    concept: str
    person: str | None
    time: TimeKey
    fields: tuple[str, ...]
    base: ResultValue | None
    scenario: ResultValue | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_id": self.value_id,
            "concept": self.concept,
            "person": self.person,
            "time": self.time.to_dict(),
            "fields": list(self.fields),
            "base": _difference_side(self.base),
            "scenario": _difference_side(self.scenario),
        }


def _difference_side(v: ResultValue | None) -> dict[str, Any] | None:
    if v is None:
        return None
    return {"value": _value_to_json(v.value), "states": [s.value for s in ordered_states(v.states)]}


_DIFF_FIELDS: tuple[tuple[str, Callable[[ResultValue], Any]], ...] = (
    ("value", lambda v: _value_to_json(v.value)),
    ("states", lambda v: frozenset(v.states)),
    ("undetermined", lambda v: None if v.undetermined is None else v.undetermined.to_dict()),
    ("out_of_scope", lambda v: None if v.out_of_scope is None else v.out_of_scope.to_dict()),
)


def scenario_differences(base: Iterable[ResultValue], scenario: Iterable[ResultValue]) -> tuple[ValueDifference, ...]:
    """2つのシナリオの値の差（値の ID で突き合わせる。値・状態・未確定の説明・対象外の理由のどれかが違うもの）。

    並びはシナリオの値の順、その後に base にだけある値（base の順）。根拠・依存・事実の ID の違いは差にしない
    （値と状態が同じなら後続の処理は変わらない：D22 S2）。
    """
    b = {v.id: v for v in base}
    out: list[ValueDifference] = []
    seen: set[str] = set()
    for v in scenario:
        seen.add(v.id)
        w = b.get(v.id)
        if w is None:
            out.append(ValueDifference(v.id, v.concept, v.person, v.time, ("present",), None, v))
            continue
        fields = tuple(name for name, f in _DIFF_FIELDS if f(v) != f(w))
        if fields:
            out.append(ValueDifference(v.id, v.concept, v.person, v.time, fields, w, v))
    for vid, w in b.items():
        if vid not in seen:
            out.append(ValueDifference(vid, w.concept, w.person, w.time, ("present",), w, None))
    return tuple(out)


def _forms_json(item: Any, ref: BasisRef | None) -> dict[str, Any]:
    """欄の値（forms.FormsResult・FormsRefusal）の JSON。欄の様式の根拠は根拠の一覧の番号にする。"""
    d = item.to_dict()
    if ref is not None and d.get("ok"):
        for form, fd in zip(item.forms, d["forms"]):
            for f, ff in zip(form.fields, fd["fields"]):
                ff["basis"] = ref(f.basis)
    return d


@dataclass(frozen=True)
class ScenarioResult:
    """シナリオ1つの結果。differences は差分なしのシナリオ（base）との値の差（base 自身は空）。
    forms は問いが欄の値を求めたときの、申告者 × 年分ごとの欄の値（forms.FormsResult か FormsRefusal）。"""

    id: str
    label: str | None
    values: tuple[ResultValue, ...]
    boundaries: tuple[Boundary, ...]
    out_of_scope: tuple[OutOfScopeItem, ...]
    filing: tuple[FilingEntry, ...]
    withheld: tuple[Withheld, ...]
    differences: tuple[ValueDifference, ...] = ()
    forms: tuple[Any, ...] = ()
    age_boundaries: tuple[AgeBoundary, ...] = ()  # 年齢の境目の説明（2026-11-12）

    def __post_init__(self) -> None:
        ids = [v.id for v in self.values]
        if len(ids) != len(set(ids)):
            raise ValueError("値の ID が重複している")
        known = set(ids)
        for v in self.values:
            for d in v.depends_on:
                if d not in known:
                    raise ValueError(f"{v.id}: 依存先 {d} がない")
        by_id = {v.id: v for v in self.values}
        for f in self.filing:
            src = by_id[f.value_id]
            if src.states & FILING_BLOCKING_STATES:  # build_filing の不変条件の二重の守り
                raise ValueError(f"{f.value_id}: 止める状態の値が申告用の値に入っている")

    def value(self, concept: str, person: str, time: TimeKey) -> ResultValue:
        for v in self.values:
            if v.concept == concept and v.person == person and v.time == time:
                return v
        raise KeyError((concept, person, time))

    def to_dict(self, ref: BasisRef | None = None) -> dict[str, Any]:
        """JSON にできる形。ref は根拠の一覧の番号（EvaluationResult.to_dict が渡す。省略は根拠の項目をそのまま書く）。"""
        return {
            "id": self.id,
            "label": self.label,
            "values": [v.to_dict(ref) for v in self.values],
            "boundaries": [b.to_dict(ref) for b in self.boundaries],
            "age_boundaries": [b.to_dict(ref) for b in self.age_boundaries],
            "out_of_scope": [o.to_dict() for o in self.out_of_scope],
            "filing": {
                "entries": [f.to_dict() for f in self.filing],
                "withheld": [w.to_dict() for w in self.withheld],
            },
            "differences": [d.to_dict() for d in self.differences],
            "forms": [_forms_json(f, ref) for f in self.forms],
        }


@dataclass(frozen=True)
class EvaluationResult:
    """評価の成功。versions は版（判定コア・openfisca-core・numpy・パラメータとデータの SHA-256・入力の SHA-256）。"""

    versions: Mapping[str, Any]
    query: Mapping[str, Any]
    injected: tuple[Mapping[str, Any], ...]
    scenarios: tuple[ScenarioResult, ...]

    ok = True

    def scenario(self, scenario_id: str) -> ScenarioResult:
        for s in self.scenarios:
            if s.id == scenario_id:
                return s
        raise KeyError(scenario_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON にできる形。根拠は全部のシナリオで共有する一覧 basis に1回だけ置き、値などからは番号で引く。"""
        table = BasisTable()
        scenarios = [s.to_dict(table.ref) for s in self.scenarios]
        return {
            "ok": True,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "versions": dict(self.versions),
            "query": dict(self.query),
            "injected": [dict(i) for i in self.injected],
            "basis": table.to_list(),
            "scenarios": scenarios,
        }


@dataclass(frozen=True)
class Problem:
    """入力の誤り（path・code・message）。okura_ir.Problem と同じ形。"""

    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class EvaluationFailure:
    """評価の失敗（入力の誤り・判定コアの誤り）。結果の値は出さない。"""

    errors: tuple[Problem, ...]

    ok = False

    def __post_init__(self) -> None:
        if not self.errors:
            raise ValueError("失敗には誤りが1つ以上要る")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "errors": [e.to_dict() for e in self.errors],
        }


SCHEMA_FILE = Path(__file__).resolve().parent / "schema" / "result.schema.json"


def load_result_schema() -> dict[str, Any]:
    """結果の JSON Schema（呼ぶたびに新しい dict）。"""
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def check_result_json(obj: Any) -> list[Any]:
    """結果の JSON（to_dict() の値）を result.schema.json で検査し、問題（okura_ir.Problem）の一覧を返す。"""
    from okura_ir.jsonschema_subset import evaluate as _evaluate_schema

    schema = load_result_schema()
    return list(_evaluate_schema(obj, schema).problems)


def dumps(result: EvaluationResult | EvaluationFailure) -> str:
    """決定的な JSON（キーを並べ替え、ASCII に逃がさない）。末尾に改行。"""
    return json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=1) + "\n"

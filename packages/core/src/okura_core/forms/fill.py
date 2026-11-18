"""対応表から欄ごとの値を作る純粋関数（SCOPE §3・§6-1、HANDOFF D19・D21 R2、design-output §6.3）。

fill_forms(結果の値, 申告者, 年分) → FormsResult か FormsRefusal。

- 入力は判定コアの結果の値（result.ResultValue：概念 ID・人・時点・値・状態・根拠）。対応表は計算しない（写す・様式の小計の和・条件だけ）。
- 予測（D19 の見込み）：その申告者・年分の申告の範囲の値か、欄が使う値に「予測」があれば、全部を出さない（FormsRefusal）。
- 見積り（法令が求める見積り）：印つきで出す。計画（申告の計画）：条件つきで出す（D21 R2）。
- 未確定：欄の状態を未確定にし、値は幅（YenRange）か None のまま出す。何で決まるかは結果の値（value_ids）の undetermined にある。
- 対象外：欄の状態を対象外にし、理由を写す。
- 令和8年分は様式が未公表なので「未公表」として拒否する（決める手段は公表待ち）。一覧にない年分は「年分外」。
- 様式に印字された式（検査）と単位（0000 などの印字）を満たさなければ「食い違い」として、その申告者・年分の欄を出さない（YH3）。

申告の型（通常・第三表あり・損失申告。YH4）は determine_filing_type が結果の値から決める。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..basis import BasisEntry, BasisType, SourceKind
from ..money import YenRange
from ..result import (
    Category,
    Count,
    DateValue,
    Flag,
    Means,
    ResultValue,
    State,
    TimeKey,
    YenAmount,
    ordered_states,
)
from .rows import ASSIGNED, MISSING, RowAssignment, assign_rows
from .table import (
    FILING_TYPES,
    FISCAL_YEAR_PREFIX,
    KAMOKU_FILE,
    YEAR_UNPUBLISHED,
    Case,
    FieldSpec,
    FormTable,
    Outcome,
    Predicate,
    YearTables,
    decode_override,
    load_year,
)

#: 令和の元年の前の年（令和 N 年 ＝ 西暦 N＋2018 年）。
REIWA_OFFSET = 2018

#: 出力する印（見積り・計画）と、その条件の文（result.FilingEntry と同じ文）。
_MARK_CONDITIONS: Mapping[State, str] = {
    State.PLAN: "申告の計画どおりに申告すること（計画）",
    State.ESTIMATE: "法令が求める見積りによる値（見積り）",
}

# 申告の型を決める概念（yoshiki-mapping-table H4）。
_LOSS = ("所得税.純損失の金額", "所得税.翌年以後に繰り越す雑損失の金額")
_CARRIED = (
    ("所得税.繰り越された純損失の金額", "所得税.純損失の繰越控除額"),
    ("所得税.繰り越された雑損失の金額", "所得税.雑損失の繰越控除額"),
)
_SEPARATE = (
    "所得税.退職所得の金額",
    "所得税.上場株式等に係る配当所得等の金額",
    "所得税.上場株式等に係る譲渡所得等の金額",
    "所得税.上場株式等の譲渡損失の繰越控除額",
)
_TYPE_REFERENCES = (
    "docs/hypotheses/20261109_round2_yoshiki-mapping-table.md#H4",
    "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#5.3",
)


class FieldStatus(enum.Enum):
    OUTPUT = "出力"  # 値を出す（見積り・計画の印・条件つきを含む）
    BLANK = "空欄"  # 書かない（記入の条件・申告の型）
    UNDETERMINED = "未確定"  # 値は幅か None
    OUT_OF_SCOPE = "対象外"  # 判定コアの値が対象外
    MISSING = "値なし"  # 結果にその概念の値がない（問いで求めていないなど）
    NO_CONCEPT = "対応なし"  # 対応する概念がない（区分：事実・判断・対象外・未対応・未決）
    NOT_OUTPUT = "出力しない"  # 個人番号・還付金の受取口座など


class RefusalCategory(enum.Enum):
    FORECAST = "予測"
    UNPUBLISHED = "未公表"
    OUT_OF_YEARS = "年分外"
    MISMATCH = "食い違い"
    BEFORE_ENFORCEMENT = "施行日前の提出"  # 提出日が使った規定の施行日より前（result.build_filing と同じ判定。forms_output が使う）


FieldValueType = int | YenRange | str | bool | _dt.date | None


def _json_value(v: Any) -> Any:
    if isinstance(v, YenRange):
        return v.to_dict()
    if isinstance(v, _dt.date):
        return v.isoformat()
    return v


@dataclass(frozen=True)
class FieldValue:
    """欄ごとの値（欄値表の行。design-output §6.3）。根拠は様式の根拠と、写した結果の値の ID（値の根拠は結果の側にある）。"""

    form: str
    position: str
    value_type: str
    status: FieldStatus
    value: FieldValueType
    basis: BasisEntry
    mapping_kind: str
    number: str | None = None
    code: str | None = None
    name: str | None = None
    row: int | None = None
    marks: frozenset[State] = frozenset()
    conditions: tuple[str, ...] = ()
    value_ids: tuple[str, ...] = ()
    category: str | None = None  # 対応なしの区分・未確定の決める手段
    reason: str | None = None
    subject: str | None = None  # 行の区画の欄：その行に割り当てた人（rows.assign_rows）
    # 2026-11-13：欄の単位（対応表の「単位」。1・100・1000・10000）。value はいつも円。欄に書くのは value ÷ unit
    # （例：第二表の「特親」は万円単位〔記入要領 001-1〕で unit=10000、630000 円なら「63」）。作成コーナーとの照合で、
    # 単位が結果に出ていないため利用アプリが円の値をそのまま書き写すおそれがあると分かった（docs/hypotheses/20261113_sakusei-reconcile_form-differences.md H4）
    unit: int = 1

    def __post_init__(self) -> None:
        if self.marks - set(_MARK_CONDITIONS):
            raise ValueError(f"{self.form}/{self.position}: 欄の印は見積り・計画だけ")
        if self.status is not FieldStatus.UNDETERMINED and isinstance(self.value, YenRange):
            raise ValueError(f"{self.form}/{self.position}: 幅は未確定の欄だけ")
        if self.status not in (FieldStatus.OUTPUT, FieldStatus.UNDETERMINED) and self.value is not None:
            raise ValueError(f"{self.form}/{self.position}: 値を出すのは出力・未確定の欄だけ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "position": self.position,
            "number": self.number,
            "code": self.code,
            "name": self.name,
            "row": self.row,
            "value_type": self.value_type,
            "unit": self.unit,
            "status": self.status.value,
            "value": _json_value(self.value),
            "marks": [s.value for s in ordered_states(self.marks)],
            "conditions": list(self.conditions),
            "value_ids": list(self.value_ids),
            "mapping": self.mapping_kind,
            "category": self.category,
            "reason": self.reason,
            "subject": self.subject,
            "basis": self.basis.to_dict(),
        }


@dataclass(frozen=True)
class FormOutput:
    """帳票ごとの欄の値。use：使う（True）か、使うかが未確定（None）。"""

    form: str
    name: str
    use: bool | None
    fields: tuple[FieldValue, ...]
    use_value_ids: tuple[str, ...] = ()
    use_reason: str | None = None
    rows: tuple[RowAssignment, ...] = ()  # この帳票の行の区画の割当て（あふれ overflow を含む）

    def field_at(self, position: str) -> FieldValue:
        for f in self.fields:
            if f.position == position:
                return f
        raise KeyError(position)

    def row_assignment(self, section: str) -> RowAssignment:
        for r in self.rows:
            if r.section == section:
                return r
        raise KeyError(section)

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "name": self.name,
            "use": self.use,
            "use_value_ids": list(self.use_value_ids),
            "use_reason": self.use_reason,
            "rows": [r.to_dict() for r in self.rows],
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass(frozen=True)
class FilingType:
    """申告の型（YH4）。value が None なら未確定（reason）。"""

    value: str | None
    value_ids: tuple[str, ...]
    reason: str | None = None
    states: frozenset[State] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "value_ids": list(self.value_ids),
            "reason": self.reason,
            "references": list(_TYPE_REFERENCES),
        }


@dataclass(frozen=True)
class FormsResult:
    person: str
    tax_year: int
    filing_type: FilingType
    forms: tuple[FormOutput, ...]
    not_produced: tuple[tuple[str, str], ...] = ()  # (帳票, 理由)

    ok = True

    def form(self, form_id: str) -> FormOutput:
        for f in self.forms:
            if f.form == form_id:
                return f
        raise KeyError(form_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "person": self.person,
            "tax_year": self.tax_year,
            "filing_type": self.filing_type.to_dict(),
            "forms": [f.to_dict() for f in self.forms],
            "not_produced": [{"form": f, "reason": r} for f, r in self.not_produced],
        }


@dataclass(frozen=True)
class FormsRefusal:
    """欄の値を出さない（予測・未公表・年分外・食い違い）。"""

    person: str
    tax_year: int
    category: RefusalCategory
    reason: str
    blocking_value_ids: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    means: Means | None = None

    ok = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "person": self.person,
            "tax_year": self.tax_year,
            "category": self.category.value,
            "reason": self.reason,
            "means": None if self.means is None else self.means.value,
            "blocking_value_ids": list(self.blocking_value_ids),
            "problems": list(self.problems),
            "references": list(self.references),
        }


# ---------------------------------------------------------------------------
# 値の読み
# ---------------------------------------------------------------------------


def _plain(v: Any) -> FieldValueType:
    if v is None or isinstance(v, YenRange):
        return v
    if isinstance(v, YenAmount):
        return v.amount
    if isinstance(v, Flag):
        return v.value
    if isinstance(v, Count):
        return v.value
    if isinstance(v, Category):
        return v.value
    if isinstance(v, DateValue):
        return v.on
    raise TypeError(f"欄に写せない値: {type(v).__name__}")


@dataclass
class _Acc:
    """欄の評価で集めたもの。"""

    ids: list[str] = field(default_factory=list)
    states: set[State] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)  # 理由

    def use(self, rv: ResultValue) -> None:
        if rv.id not in self.ids:
            self.ids.append(rv.id)
        self.states |= set(rv.states)
        if State.OUT_OF_SCOPE in rv.states:
            reason = rv.out_of_scope.reason if rv.out_of_scope else "対象外"
            self.out_of_scope.append(f"{rv.concept}：{reason}")


class _Ctx:
    def __init__(
        self,
        values: Mapping[str, ResultValue],
        tax_year: int,
        filing_type: FilingType,
        *,
        person: str = "",
        year_values: tuple[ResultValue, ...] = (),
        fiscal_values: Mapping[str, ResultValue] | None = None,
    ) -> None:
        self.values = values
        self.fiscal_values = fiscal_values or {}  # 申告者の年分＋1 の年度の値（住民税の概念。行の区画の人には使わない）
        self.tax_year = tax_year
        self.filing_type = filing_type
        self.forecast: set[str] = set()
        self.person = person
        self.year_values = year_values  # その年分の全員の値（行の割当てと、行の人の値を読むため）
        self._rows: dict[tuple[str, int], RowAssignment] = {}

    def assignment(self, section: str, capacity: int) -> RowAssignment:
        key = (section, capacity)
        if key not in self._rows:
            a = assign_rows(section, capacity, self.year_values, self.person)
            self._rows[key] = a
            if State.FORECAST in a.states:
                by_id = {v.id: v for v in self.year_values}
                self.forecast |= {i for i in a.value_ids if State.FORECAST in by_id[i].states}
        return self._rows[key]

    def for_person(self, person: str) -> _Ctx:
        """行の人の値を読む窓口（予測の検出は共有する）。"""
        sub = _Ctx(
            {v.concept: v for v in reversed(self.year_values) if v.person == person},
            self.tax_year,
            self.filing_type,
            person=person,
            year_values=self.year_values,
        )
        sub.forecast = self.forecast
        return sub

    def get(self, concept: str, acc: _Acc) -> ResultValue | None:
        """概念の値。「住民税.」の概念は年分＋1 の年度の値（第二表の住民税に関する事項：forms/README.md §3）。"""
        rv = (self.fiscal_values if concept.startswith(FISCAL_YEAR_PREFIX) else self.values).get(concept)
        if rv is None:
            acc.missing.append(concept)
            return None
        acc.use(rv)
        if State.FORECAST in rv.states:
            self.forecast.add(rv.id)
        return rv


def _truth(test: str, v: FieldValueType, equals: str | None) -> bool | None:
    """条件の判定。幅なら全部で同じときだけ決まる。値がなければ None（未確定）。"""
    if v is None:
        return None
    if test in ("真", "偽"):
        if not isinstance(v, bool):
            raise TypeError(f"真偽の判定に {type(v).__name__}")
        return v if test == "真" else not v
    if test == "等しい":
        if not isinstance(v, str):
            raise TypeError(f"区分の判定に {type(v).__name__}")
        return v == equals
    lo, hi = (v.min, v.max) if isinstance(v, YenRange) else (v, v)
    if isinstance(lo, bool) or not isinstance(lo, int):
        raise TypeError(f"金額の判定に {type(v).__name__}")
    if test == "正":
        return True if lo > 0 else False if hi <= 0 else None
    if test == "負":
        return True if hi < 0 else False if lo >= 0 else None
    if test == "零":
        return True if lo == hi == 0 else False if (lo > 0 or hi < 0) else None
    if test == "非零":
        return False if lo == hi == 0 else True if (lo > 0 or hi < 0) else None
    raise ValueError(test)


def _eval_pred(p: Predicate, ctx: _Ctx, acc: _Acc) -> bool | None:
    if p.kind == "型":
        ft = ctx.filing_type
        acc.ids += [i for i in ft.value_ids if i not in acc.ids]
        acc.states |= set(ft.states)
        return None if ft.value is None else ft.value == p.filing_type
    if p.kind == "いずれか":
        results = [_eval_pred(x, ctx, acc) for x in p.any_of]
        if any(r is True for r in results):
            return True
        return False if all(r is False for r in results) else None
    assert p.concept is not None and p.test is not None
    rv = ctx.get(p.concept, acc)
    if rv is None or State.OUT_OF_SCOPE in rv.states:
        return None
    return _truth(p.test, _plain(rv.value), p.equals)


def _eval_all(preds: Iterable[Predicate], ctx: _Ctx, acc: _Acc) -> bool | None:
    """すべて満たすか。どれかが偽なら偽、決まらないものがあれば None。"""
    results = [_eval_pred(p, ctx, acc) for p in preds]
    if any(r is False for r in results):
        return False
    return None if any(r is None for r in results) else True


# ---------------------------------------------------------------------------
# 欄
# ---------------------------------------------------------------------------


def _basis(table: FormTable, spec: FieldSpec) -> BasisEntry:
    return BasisEntry(
        type=BasisType.RULE,
        name=f"様式 {table.yoshiki_number}（{table.form}）{spec.position}",
        source_kind=SourceKind.CIRCULAR,
        references=tuple(dict.fromkeys(table.references + spec.references)),
        law=table.form_basis,
        detail={
            "記載事項の根拠": table.items_basis,
            "対応の仮説": list(table.hypotheses),
            "欄コード": spec.code,
            "欄番号": spec.number,
        },
    )


def _sum(values: list[FieldValueType]) -> FieldValueType:
    if any(v is None for v in values):
        return None
    lo = hi = 0
    for v in values:
        if isinstance(v, YenRange):
            lo, hi = lo + v.min, hi + v.max
        elif isinstance(v, bool) or not isinstance(v, int):
            raise TypeError(f"合計に金額でない値: {type(v).__name__}")
        else:
            lo, hi = lo + v, hi + v
    return lo if lo == hi else YenRange(lo, hi)


def _select(cases: Iterable[Case], ctx: _Ctx, acc: _Acc) -> Outcome | None | bool:
    """最初に条件をすべて満たす場合の結果。条件が決まらなければ None、どの場合にも当たらなければ False。"""
    for case in cases:
        r = _eval_all(case.when, ctx, acc)
        if r is True:
            return case.outcome
        if r is None:
            return None
    return False


def _field(table: FormTable, spec: FieldSpec, ctx: _Ctx) -> FieldValue:
    acc = _Acc()
    base = dict(
        form=table.form,
        position=spec.position,
        value_type=spec.value_type,
        basis=_basis(table, spec),
        mapping_kind=spec.mapping.kind,
        number=spec.number,
        code=spec.code,
        name=spec.name,
        row=spec.row,
        unit=spec.unit,
    )
    if spec.section is not None and spec.capacity is not None and spec.row is not None:
        a = ctx.assignment(spec.section, spec.capacity)
        if a.status != ASSIGNED:
            acc.ids += list(a.value_ids)
            acc.states |= set(a.states) & set(_MARK_CONDITIONS)
            status = FieldStatus.MISSING if a.status == MISSING else FieldStatus.UNDETERMINED
            return FieldValue(
                **base,
                status=status,
                value=None,
                value_ids=tuple(acc.ids),
                category="行の割当て",
                reason=f"「{spec.section}」の行の割当てが{a.status}：{a.reason}",
            )
        subject = a.person_at(spec.row)
        if subject is None:
            return FieldValue(**base, status=FieldStatus.BLANK, value=None, value_ids=a.value_ids, reason=f"「{spec.section}」のこの行に載せる人がいない")
        return dataclasses.replace(_field_for(table, spec, ctx.for_person(subject), base, _Acc(ids=list(a.value_ids))), subject=subject)
    return _field_for(table, spec, ctx, base, acc)


def _field_for(table: FormTable, spec: FieldSpec, ctx: _Ctx, base: Mapping[str, Any], acc: _Acc) -> FieldValue:

    def make(status: FieldStatus, value: FieldValueType = None, *, category: str | None = None, reason: str | None = None) -> FieldValue:
        marks = frozenset(acc.states & set(_MARK_CONDITIONS))
        return FieldValue(
            **base,
            status=status,
            value=value,
            marks=marks,
            conditions=tuple(_MARK_CONDITIONS[s] for s in ordered_states(marks)),
            value_ids=tuple(acc.ids),
            category=category,
            reason=reason,
        )

    def blocked() -> FieldValue | None:
        if acc.out_of_scope:
            return make(FieldStatus.OUT_OF_SCOPE, reason="・".join(acc.out_of_scope))
        if acc.missing:
            return make(FieldStatus.MISSING, reason="結果に値がない概念：" + "・".join(dict.fromkeys(acc.missing)))
        return None

    if spec.blank_in:
        ft = ctx.filing_type
        if ft.value is None:
            acc.ids += list(ft.value_ids)
            return make(FieldStatus.UNDETERMINED, category="申告の型", reason="申告の型が未確定：" + (ft.reason or ""))
        if ft.value in spec.blank_in:
            return make(FieldStatus.BLANK, reason=f"申告の型「{ft.value}」ではこの欄を記入しない（yoshiki-mapping-table H4）")

    cases = spec.mapping.cases
    if spec.mapping.kamoku is not None:
        # 利用者の科目の割当ての選択（選択.様式への割当て C-18：rules/income_kinds/form_override.py。README §4.1）。結果に値がなければ既定の割当て
        # （income_kinds は全員に「なし」か選択を書き、forms_output.form_specs はこの概念を欄が読む概念として結果に出す）
        k = spec.mapping.kamoku
        rv = ctx.get(k.override_concept, acc) if k.override_concept in ctx.values else None
        if rv is not None:
            stop = blocked()
            if stop is not None:
                return stop
            plain = _plain(rv.value)
            if State.UNDETERMINED in rv.states or not isinstance(plain, str):
                return make(FieldStatus.UNDETERMINED, category="科目の割当て", reason="科目の割当ての選択（どの業務の表に当てるか）が未確定")
            override = decode_override(plain)
            keys = k.keys(override) if override is not None else None
            if keys is None:
                return make(FieldStatus.OUT_OF_SCOPE, reason=f"{k.override_concept} の値 {plain!r} が科目の割当ての表（{KAMOKU_FILE}）の費目で読めない")
            if override:
                cases = k.cases(keys)
    selected = _select(cases, ctx, acc)
    stop = blocked()
    if stop is not None:
        return stop
    if selected is None:
        return make(FieldStatus.UNDETERMINED, category="条件", reason="対応の条件の値が未確定")
    if selected is False:
        return make(FieldStatus.BLANK, reason="対応の条件のどれにも当たらない")
    o = selected
    if o.kind in ("そのまま", "合計"):
        rvs = [ctx.get(c, acc) for c in o.concepts]
        stop = blocked()
        if stop is not None:
            return stop
        copied = [rv for rv in rvs if rv is not None]
        plain = [_plain(rv.value) for rv in copied]
        value = plain[0] if o.kind == "そのまま" else _sum(plain)
        if value is None or isinstance(value, YenRange) or any(State.UNDETERMINED in rv.states for rv in copied):
            # 幅は申告書の欄に書けない（build_filing の「幅」と同じ）。何で決まるかは value_ids の値の undetermined にある
            reason = "幅（根拠のない端数などで金額が1つに決まらない）" if isinstance(value, YenRange) else "写した値が未確定"
            return make(FieldStatus.UNDETERMINED, value, category="結果の値", reason=reason)
        return make(FieldStatus.OUTPUT, value)
    if o.kind == "値":
        return make(FieldStatus.OUTPUT, o.value)
    if o.kind == "問い":
        return make(FieldStatus.OUTPUT, str(ctx.tax_year - REIWA_OFFSET))
    if o.kind == "空欄":
        return make(FieldStatus.BLANK, reason=o.reason)
    if o.kind == "未確定":
        return make(FieldStatus.UNDETERMINED, category=Means.PRIMARY_SOURCE.value, reason=o.reason)
    if o.category == "出力しない":
        return make(FieldStatus.NOT_OUTPUT, category=o.category, reason=o.reason)
    return make(FieldStatus.NO_CONCEPT, category=o.category, reason=o.reason)


# ---------------------------------------------------------------------------
# 申告の型
# ---------------------------------------------------------------------------


def determine_filing_type(values: Mapping[str, ResultValue]) -> FilingType:
    """申告の型（YH4）：純損失・その年の雑損失の繰越があれば損失申告、分離課税の所得・退職所得があれば第三表あり、ほかは通常。

    前年以前の損失のうちその年に控除しきれない残りがある（繰り越された額 ＞ 繰越控除額）ときは、翌年以後に繰り越すか
    （第四表が要るか）を決める概念がないので未確定。値がない・対象外・決まらない値があっても未確定。
    """
    ids: list[str] = []
    states: set[State] = set()

    def read(cid: str) -> tuple[FieldValueType, str | None]:
        rv = values.get(cid)
        if rv is None:
            return None, f"結果に {cid} の値がない"
        ids.append(rv.id)
        states.update(rv.states)
        if State.OUT_OF_SCOPE in rv.states:
            return None, f"{cid} が対象外"
        return _plain(rv.value), None

    def undetermined(reason: str) -> FilingType:
        return FilingType(None, tuple(ids), reason, frozenset(states))

    loss: list[bool | None] = []
    for cid in _LOSS:
        v, why = read(cid)
        if why:
            return undetermined(why)
        loss.append(_truth("正", v, None))
    if any(x is True for x in loss):
        return FilingType("損失申告", tuple(ids), None, frozenset(states))
    if any(x is None for x in loss):
        return undetermined("損失の額が未確定")
    for carried_id, used_id in _CARRIED:
        carried, why1 = read(carried_id)
        used, why2 = read(used_id)
        if why1 or why2:
            return undetermined(why1 or why2 or "")
        if carried is None or used is None or isinstance(carried, YenRange) or isinstance(used, YenRange):
            return undetermined("繰り越された損失の額が未確定")
        assert isinstance(carried, int) and isinstance(used, int)
        if carried > used:
            return undetermined(
                f"{carried_id} のうちその年に控除しきれない残りがある。翌年以後に繰り越すか（第四表が要るか）を決める概念がない"
            )
    separate: list[bool | None] = []
    for cid in _SEPARATE:
        v, why = read(cid)
        if why:
            return undetermined(why)
        separate.append(_truth("非零", v, None))
    if any(x is True for x in separate):
        return FilingType("第三表あり", tuple(ids), None, frozenset(states))
    if any(x is None for x in separate):
        return undetermined("分離課税の所得・退職所得の額が未確定")
    return FilingType("通常", tuple(ids), None, frozenset(states))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _checks(table: FormTable, out: FormOutput) -> list[str]:
    problems: list[str] = []
    for f in out.fields:
        spec = table.field_at(f.position)
        if f.status is FieldStatus.OUTPUT and spec.unit > 1 and isinstance(f.value, int) and not isinstance(f.value, bool):
            if f.value % spec.unit:
                problems.append(f"{table.form}/{f.position}: 値 {f.value} が単位（{spec.unit} 円）の倍数でない")
    for c in table.checks:
        operands = [out.field_at(p) for p in (c.left, *c.right)]
        if not all(o.status is FieldStatus.OUTPUT and type(o.value) is int for o in operands):
            continue  # 値を出さない欄があれば確かめない
        left, *right = (o.value for o in operands)
        assert isinstance(left, int)
        rhs = sum(right) if c.kind == "合計" else right[0] - sum(right[1:])  # type: ignore[operator]
        if left != rhs:
            problems.append(f"{table.form}: 様式の式（{c.note or c.kind}）を満たさない：{c.left}＝{left}、右辺＝{rhs}")
    return problems


def fill_forms(
    values: Iterable[ResultValue], person: str, tax_year: int, *, tables: YearTables | None = None
) -> FormsResult | FormsRefusal:
    """申告者・年分の欄ごとの値を作る（純粋関数）。values は判定コアの結果の値（ほかの人・時点の値が混ざってよい）。

    所得税の概念の欄は年分 tax_year の値、住民税の概念（「住民税.」）の欄は年度 tax_year＋1 の申告者の値を写す（なければ値なし）。

    tables はテストのための差し替え（既定は load_year(tax_year)）。
    """
    if tables is None:
        tables = load_year(tax_year)
    if tables is None:
        return FormsRefusal(
            person, tax_year, RefusalCategory.OUT_OF_YEARS, f"{tax_year}年分の様式の欄の対応表はない（SCOPE §5：令和7年分・令和8年分）"
        )
    if tables.status == YEAR_UNPUBLISHED:
        return FormsRefusal(
            person,
            tax_year,
            RefusalCategory.UNPUBLISHED,
            tables.reason or "様式が未公表",
            references=tables.references,
            means=Means.AWAITING_PUBLICATION,
        )
    time = TimeKey("tax_year", tax_year)
    values_list = tuple(values)
    year_values = tuple(v for v in values_list if v.time == time)
    mine = [v for v in year_values if v.person == person]
    by_concept: dict[str, ResultValue] = {}
    for v in mine:
        by_concept.setdefault(v.concept, v)
    forecast = {v.id for v in mine if v.filing_scope and State.FORECAST in v.states}
    # 住民税の概念の欄は、その年分の所得で課する年度（年分＋1）の申告者の値を読む（table.FISCAL_YEAR_PREFIX）
    fiscal_time = TimeKey("fiscal_year", tax_year + 1)
    fiscal: dict[str, ResultValue] = {}
    for v in values_list:
        if v.time == fiscal_time and v.person == person:
            fiscal.setdefault(v.concept, v)

    filing_type = determine_filing_type(by_concept)
    ctx = _Ctx(by_concept, tax_year, filing_type, person=person, year_values=year_values, fiscal_values=fiscal)
    forms: list[FormOutput] = []
    not_produced: list[tuple[str, str]] = []
    problems: list[str] = []
    for table in tables.forms:
        if table.use_by_facts:
            not_produced.append((table.form, "使うかは入力の事実（明細の行の数など）で決まる。利用アプリが決める"))
            continue
        use: bool | None = True
        use_reason: str | None = None
        if filing_type.value is not None and filing_type.value not in table.filing_types:
            not_produced.append((table.form, f"申告の型「{filing_type.value}」では使わない"))
            continue
        acc = _Acc()
        if filing_type.value is None and table.filing_types != frozenset(FILING_TYPES):
            use, use_reason = None, "申告の型が未確定"
            acc.ids += list(filing_type.value_ids)
        if table.use_when:
            r = _eval_all(table.use_when, ctx, acc)
            if r is False:
                not_produced.append((table.form, "使う条件を満たさない"))
                continue
            if r is None or acc.missing or acc.out_of_scope:
                use, use_reason = None, "使う条件の値が未確定・値なし・対象外"
        fields = tuple(_field(table, spec, ctx) for spec in table.fields)
        sections = sorted({(s.section, s.capacity) for s in table.fields if s.section is not None and s.capacity is not None})
        rows = tuple(ctx.assignment(sec, cap) for sec, cap in sections)
        out = FormOutput(table.form, table.name, use, fields, tuple(acc.ids), use_reason, rows)
        problems += _checks(table, out)
        forms.append(out)

    forecast |= ctx.forecast
    if forecast:
        return FormsRefusal(
            person,
            tax_year,
            RefusalCategory.FORECAST,
            "予測（見込み）を含む値から申告用の値は出さない（HANDOFF D19・D21 R2）",
            blocking_value_ids=tuple(sorted(forecast)),
        )
    if problems:
        return FormsRefusal(
            person,
            tax_year,
            RefusalCategory.MISMATCH,
            "判定コアの値が様式の式・単位を満たさない（yoshiki-mapping-table H3）。欄の値を出さない",
            problems=tuple(problems),
        )
    return FormsResult(person, tax_year, filing_type, tuple(forms), tuple(not_produced))

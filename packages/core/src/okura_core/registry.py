"""規則モジュールの登録（packages/core/README.md §10「規則モジュールの足し方」）。

規則モジュール（okura_core/rules/<名前>/）は、次を宣言した RuleModule を `MODULE` として持つ：

- 変数（OpenFisca の Variable のクラス）            RuleModule.variables
- パラメータ（YAML）と表のデータ                    <ディレクトリ>/parameters/・<ディレクトリ>/data/（build_system が木を合わせる）
- 概念辞書の項目                                    <ディレクトリ>/concepts.yaml（concepts.load_dictionary が読む。先頭に 担当: <名前>）
- 使う中間表現の記録の種類と situation への写し方    record_kinds と build_inputs（入力変数の値と由来・対象外の検出）
- 使う判断・選択の種類と、未入力のときの候補        decisions（DecisionSpec。D21 R6）
- 根拠のない端数の候補評価                          roundings（RoundingSlotSpec。D22 S3）
- 法令の読みの候補評価（金額なら幅）                readings（ReadingSlotSpec。D22 S1・S3）
- 注入データ（市町村・保険者）から来る値と、未注入のときの候補  injections（InjectionSpec。D17・D19・D21 R6）
- グループ（扶養所属など）の組み立て                groups
- 段階評価（人をまたぐ関係を前の段の値から決める）  stages（StageSpec。D23 K1）
- 計算の後の対象外の検出                            checks（CheckContext → ValueExclusion）
- 規則の根拠                                        rules（パラメータでない規則）・basis（根拠の組み立てを自分で行う変数）
- 境目の説明                                        concepts.yaml の「境目」

登録は rules/__init__.py の1行（`from .<名前> import MODULE as <名前>`）。evaluate.py・situation.py・country/__init__.py・
概念辞書の共通部分（concepts/structure.yaml など）を触らずに規則を足せる。

このファイルは型と、登録の一覧から Registry（辞書との突き合わせ・導いた一覧。段階評価の順序を含む）を作る処理だけを持つ。法令の値・規則は持たない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .basis import BasisEntry
from .candidates import Candidate
from .concepts import Concept, ConceptDictionary, ConceptProblem, default_module_dirs, load_dictionary
from .country.entities import ENTITIES
from .query import FilingDate
from .relations import RelationView
from .result import OutOfScopeReason, Split, State
from .timepoints import Window

# ---------------------------------------------------------------------------
# モジュールが返すもの
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageValue:
    """段階の間で引いた、前の段の1人分の値（D23 K1）と、その由来。

    - value：OpenFisca の値（円・整数・真偽・区分・日付の Python の値）。対象外の値でも入っている（対象外の入力に0を入れて
      計算した値などで、信じられない。reasons を入力の由来に入れれば、依存する値へ対象外が伝わる）。
    - states・facts・reasons・basis：その値の状態（予測・見積り・計画）、使った事実の ID、対象外の理由、根拠。
    - value_ids：結果の depends_on に足す値の ID（出力の変数ならその値、途中の変数なら依存した出力の値）。
    - inputs：推移的に依存した入力（変数, 人）。候補の評価が「この値に関係する分かれ目」を決めるのに使う。
    - pending：まだ計算していない段の値（build_inputs の最初の段だけ）。value は変数の既定値。
    - missing：その値が依存する、注入されていない（候補を持たない）注入点の分かれ目（その値は未確定）。
    - extra：値そのものの入力ではないが、値の対象外の理由を変えうる入力（集め忘れの検出が見る値の入力。2026-11-12 の4回目）。
      evaluate が「この値が依存する分かれ目」を決めるのに inputs と合わせて使う（「関係する分かれ目」の表示には使わない）。
    """

    variable: str
    person: str
    value: Any
    states: frozenset[State] = frozenset()
    facts: tuple[str, ...] = ()
    value_ids: tuple[str, ...] = ()
    reasons: tuple[OutOfScopeReason, ...] = ()
    basis: tuple[BasisEntry, ...] = ()
    inputs: frozenset[tuple[str, str]] = frozenset()
    pending: bool = False
    missing: tuple[Split, ...] = ()
    extra: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True)
class InputValue:
    """入力変数の1人分の値と由来（記録・判断・選択の ID と、その印から決まる状態）。

    uses：段階の間で引いた値（StageValue）。状態・対象外・根拠・依存が、この入力に依存する値へ伝わる。
    None は未指定（段階の出力なら、その段で読んだ値の全部を使ったものとする：安全側）。
    basis：この入力を決めた規則の根拠（段階の規則・注入データの出典など）。依存する値の根拠に足す。
    missing：この入力が依存する、注入されていない（候補を持たない）注入点の分かれ目（Decided.missing）。
    依存する値は未確定になり、分かれ目（決める手段＝注入）が「何を注入すれば決まるか」になる。
    """

    value: Any
    record_ids: tuple[str, ...] = ()
    states: frozenset[State] = frozenset()
    uses: tuple[StageValue, ...] | None = None
    basis: tuple[BasisEntry, ...] = ()
    missing: tuple[Split, ...] = ()


@dataclass(frozen=True)
class Exclusion:
    """対象外の検出の結果。variable が None なら、その人・年分の全部の値（人の対象外）。

    variable を書けば、その変数（入力変数か、計算の後の検出なら式のある変数）だけを対象外にし、依存する値へ伝える。
    """

    person: str
    reason: OutOfScopeReason
    variable: str | None = None


#: 実行中の build_inputs の読みの記録（situation._reuse が入れる。2026-11-12 の4回目）：(読んだ1か所の並び, 出力のオブジェクトの id →
#: (オブジェクト, そのオブジェクトを作った時点までに読んだ数))。値はそれを書いた時点までに読んだものからしか作れない（因果）ので、
#: evaluate は入力・対象外が依存しうる分かれ目を、その時点までに読んだ1か所に限る（値ごとの候補の評価の、安全側の決め方）。
CAPTURE: list[Any] = [None]


def _captured(obj: Any) -> None:
    cap = CAPTURE[0]
    if cap is not None:
        cap[1][id(obj)] = (obj, len(cap[0]))


@dataclass
class ModuleInputs:
    """build_inputs の結果：入力変数 × 人 の値と、対象外の検出。

    モジュールが持つ入力変数（式のない変数）は、その年分に生存している全員について値を書く（書き忘れを誤りにする）。
    対象外にした入力にも値を書く（0 など。OpenFisca に渡す値で、結果には出ない）。
    set・exclude は、そのときまでに読んだ1か所の数を記録する（CAPTURE。evaluate の候補の評価が使う。値は変えない）。
    """

    values: dict[tuple[str, str], InputValue] = field(default_factory=dict)
    exclusions: list[Exclusion] = field(default_factory=list)

    def set(
        self,
        variable: str,
        person: str,
        value: Any,
        record_ids: Iterable[str] = (),
        states: Iterable[State] = (),
        *,
        uses: Iterable[StageValue] | None = None,
        basis: Iterable[BasisEntry] = (),
        missing: Iterable[Split] = (),
    ) -> None:
        key = (variable, person)
        if key in self.values:
            raise ValueError(f"入力の値を2回書いた: {key}")
        iv = self.values[key] = InputValue(
            value,
            tuple(sorted(set(record_ids))),
            frozenset(states),
            None if uses is None else tuple(uses),
            tuple(basis),
            unique_splits(missing),
        )
        _captured(iv)

    def exclude(self, person: str, reason: OutOfScopeReason, variable: str | None = None) -> None:
        e = Exclusion(person, reason, variable)
        self.exclusions.append(e)
        _captured(e)


@dataclass(frozen=True)
class GroupInstance:
    """グループ（扶養所属・法律婚・健康保険）のインスタンス1つ。roles は役割の複数形 → 人の ID。

    uses・basis は段階の出力のグループの由来（InputValue と同じ。グループを使う値に伝える）。
    """

    id: str
    roles: Mapping[str, tuple[str, ...]]
    record_ids: tuple[str, ...] = ()
    states: frozenset[State] = frozenset()
    uses: tuple[StageValue, ...] | None = None
    basis: tuple[BasisEntry, ...] = ()


def unique_splits(splits: Iterable[Split]) -> tuple[Split, ...]:
    """分かれ目を ID で重ねずに並べる（ID の順）。"""
    out: dict[str, Split] = {}
    for s in splits:
        out.setdefault(s.id, s)
    return tuple(out[k] for k in sorted(out))


@dataclass(frozen=True)
class Decided:
    """判断・選択・注入データの1か所の値。open なら未入力で、いまの評価の候補の値（record_ids・states は空）。

    注入データ（InjectionSpec）では、record_ids は注入データの項目の ID、basis はその出典（BasisType.INJECTION）。
    候補を持たない注入点が注入されていなければ value は None で、missing にその分かれ目（決める手段＝注入）が入る。
    モジュールは入力の値に仮の値（0 など）を書き、ModuleInputs.set(…, missing=d.missing) に渡す（依存する値は未確定になる）。
    """

    value: Any
    record_ids: tuple[str, ...]
    states: frozenset[State]
    open: bool
    basis: tuple[BasisEntry, ...] = ()
    missing: tuple[Split, ...] = ()


# ---------------------------------------------------------------------------
# モジュールが宣言するもの
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionSlot:
    """判断・選択が要る1か所（例：この年分の、申告者 p と親族 q が生計を一にするか）。

    - key：判断・選択の種類の中で一意な名前。同じ種類・同じ key を複数のモジュールが宣言したら同じ1か所として扱う
      （同じ判断を2通りに評価しない）。形は種類ごとに決める（例 "判断.生計を一にする" は "<person>:<other_person>"）。
    - target：結果の分かれ目（Split.target）に出す対象（人の ID・記録の ID など）。
    - matches：中間表現の判断・選択の1件（置き換えの連鎖の先頭）がこの1か所の値か。
    - candidates：未入力のときの候補。None なら中間表現の語彙の値の領域（真偽・列挙）から作る。
    - year_filter：True（既定）なら、その年分と重なる判断・選択だけを見る。False なら重ならないものも見る
      （matches がその日の判断を選ぶ1か所のときに使う。例：前年の受診日に支払った医療費の生計の判断）。
    - persons：この判断が関係する人（evaluate の人のつながりの計算に使う）。None なら target から導く
      （人の ID・記録の ID の役割の人・「:」で区切った key の部分）。誰にも結びつかなければ全部の人のつながりに入る（安全側）。
    - monotone：単調な判断の両端評価の群の名前（D21 R6）。同じ名前の未入力の1か所を「全部 候補0」と「全部 候補1」の両端だけで
      まとめて評価する（支出ごとに分かれ目があって直積が爆発する判断。候補は2つで同じ名前。モジュールは、値が群の各1か所について
      同じ向きに単調であることを保証する）。結論が同じなら断定、金額は幅、判定が分かれたら未確定。
    - lazy：読んだときだけ開く（2026-11-11）。未入力の1か所を最初は直積に入れず、build_inputs・段の関数が ctx.decision で
      読んだ候補の組があったときにだけ分かれ目として開いて評価し直す（根拠のない端数の RoundingSlotSpec(variable=None) と同じ形）。
      分かれ目になるかが段の値（所得など）で決まる1か所に使う。読まなければ値に関係しないので、結果の分かれ目にも出ない。
      monotone と一緒には使えない。
    """

    key: str
    target: Mapping[str, Any]
    matches: Callable[[Mapping[str, Any]], bool]
    candidates: tuple[Candidate, ...] | None = None
    year_filter: bool = True
    persons: tuple[str, ...] | None = None
    monotone: str | None = None
    lazy: bool = False


@dataclass(frozen=True)
class DecisionSpec:
    """使う判断・選択の種類（中間表現の kind。`判断.*`・`見込み.*`・`見積り.*`・`計画.*` は judgments、`選択.*` は choices）。

    slots(ctx) がその年分に要る1か所の一覧を返す。値は value_of(記録)（既定は記録の value）。
    """

    kind: str
    slots: Callable[[YearContext], Iterable[DecisionSlot]]
    value_of: Callable[[Mapping[str, Any]], Any] = field(default=lambda rec: rec["value"])

    @property
    def section(self) -> str:
        return "choices" if self.kind.startswith("選択.") else "judgments"


@dataclass(frozen=True)
class InjectionSlot:
    """注入データが要る1か所（例：この年度の、市町村 X の級地。D17・D19）。

    - key：注入点の中で一意な名前（同じ注入点・同じ key を複数のモジュールが宣言したら同じ1か所）。既定の形は
      injection_key(団体の種類, 団体のコード, 日付)。
    - issuer_kind・issuer_code：団体（municipality・prefecture・insurer とそのコード）。
    - on：どの日に適用される注入データを使うか（適用期間がこの日を含む項目。例：級地は前年の12月31日、保険者の運用は判定日）。
    - target：結果の分かれ目（Split.target）に足す説明（人の ID など）。
    - candidates：未注入のときの候補（None なら注入点の候補 InjectionPoint.candidates。値は中身の data）。
    - persons：関係する人（evaluate の人のつながりの計算に使う。None なら target から導く）。
    """

    key: str
    issuer_kind: str
    issuer_code: str
    on: _dt.date
    target: Mapping[str, Any] = field(default_factory=dict)
    candidates: tuple[Candidate, ...] | None = None
    persons: tuple[str, ...] | None = None


def injection_key(issuer_kind: str, issuer_code: str, on: _dt.date) -> str:
    """InjectionSlot.key の既定の形。"""
    return f"{issuer_kind}:{issuer_code}:{on.isoformat()}"


def injection_kind(point: str) -> str:
    """注入点の1か所を判断・選択と同じ道具（situation.resolve_decisions・候補の評価）で扱うときの種類の名前。"""
    return f"注入.{point}"


@dataclass(frozen=True)
class InjectionSpec:
    """使う注入点（injection_points.POINTS の名前）と、その評価の単位に要る1か所の一覧（D19・D21 R6）。

    値は YearContext.injection(point, key)（Decided）：注入されていれば中身の data（根拠に出典）、未注入なら候補の data
    （分かれ目の決める手段は「注入」。結論が同じなら断定、違えば未確定）、候補を持たない注入点なら None と missing。
    概念辞書で、このモジュールの概念の「注入データ」に point を書く（登録の時点で確かめる）。
    """

    point: str
    slots: Callable[[YearContext], Iterable[InjectionSlot]]

    @property
    def kind(self) -> str:
        return injection_kind(self.point)


@dataclass(frozen=True)
class RoundingSlotSpec:
    """根拠のない端数（D21 R5・D22 S3）。候補（floor・ceil・half_up）の名前を入力変数 variable（文字列の変数）で式に渡す。

    式は rounding.FUNCTIONS[候補の名前] で丸める。分かれ目は年分ごとに1つ（法令の読みは1つなので人をまたいで同じ候補）。
    variable が None なら入力変数を持たず、build_inputs などで YearContext.rounding_candidate／round_unfounded から候補を読む
    （読んだときだけ分かれ目を開く）。
    """

    name: str
    variable: str | None
    title: str


@dataclass(frozen=True)
class ReadingSlotSpec:
    """法令の読みの候補（D22 S1・S3。2026-11-12）：一次情報で決まらない読み（支えが同程度の2つ以上の読み）を候補の全部で評価する。

    根拠のない端数（RoundingSlotSpec）と同じまとめ方（方針 Policy.READING）：候補で金額だけが違えば幅（YenRange）で返し、
    判定（真偽・区分・整数）が分かれたときだけ未確定（決める手段は一次情報）。判断・選択の分かれ目と両方で金額が違うときは、
    判断・選択の分かれ目だけで未確定にし、候補ごとの値を読みの候補の幅にする。
    candidates は候補の名前（2つ以上。最初が既定の読み）。variable（文字列の入力変数）に今の候補の名前が入る（式は読みで値が
    違う人がいるときだけ引く）。variable が None なら build_inputs・段の関数で YearContext.reading(name) で読む（読んだときだけ開く）。
    分かれ目の ID は「読み:<name>」、対象に title と候補の説明 explanations（候補の名前 → 説明。任意）。年分ごとに1つ（人をまたいで同じ読み）。
    """

    name: str
    variable: str | None
    title: str
    candidates: tuple[str, ...]
    explanations: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckContext:
    """計算の後の対象外の検出（RuleModule.checks）に渡すもの。calc は同じ評価の OpenFisca の値（人の並びは persons）。"""

    year: int
    persons: tuple[str, ...]
    calc: Callable[[str], Any]
    parameters: Any  # その年分の1月1日の ParameterNodeAtInstant
    ir: Mapping[str, Any]
    filing_date: FilingDate | None = None  # 問いの提出日（予定日。D22 S4）


@dataclass(frozen=True)
class BasisContext:
    """根拠の組み立て（RuleModule.basis）に渡すもの。index は persons の中の位置。"""

    year: int
    instant: str
    root: Any  # パラメータの木（ParameterNode）
    parameters: Any  # その年分の1月1日の ParameterNodeAtInstant
    computed: Callable[[str], Any]
    index: int
    person: str
    filing_date: FilingDate | None = None  # 問いの提出日（予定日。D22 S4）


@dataclass(frozen=True)
class RecordKind:
    """種類より細かい record_kinds の宣言（filed_document の書類の種別など）。

    kind の記録のうち attributes[attribute] が values のどれかのものだけを「使う」とする（ほかの書類の種別は使わない記録になる）。
    """

    kind: str
    attribute: str
    values: frozenset[str]

    def matches(self, rec: Mapping[str, Any]) -> bool:
        if rec.get("kind") != self.kind:
            return False
        v = rec.get("attributes", {}).get(self.attribute)
        return isinstance(v, str) and v in self.values


class StageOutput:
    """段階の関数（StageSpec.run）の結果：入力変数の値・対象外・グループ。

    set は ModuleInputs.set と同じ（uses に引いた値を渡すと、状態・対象外・根拠・依存が依存する値へ伝わる。
    渡さなければ、その段で読んだ値の全部を使ったものとする：安全側）。
    group はグループの全部のインスタンス（生存している全員がちょうど1回）。
    """

    def __init__(self) -> None:
        self.inputs = ModuleInputs()
        self.groups: dict[str, tuple[GroupInstance, ...]] = {}

    def set(
        self,
        variable: str,
        person: str,
        value: Any,
        record_ids: Iterable[str] = (),
        states: Iterable[State] = (),
        *,
        uses: Iterable[StageValue] | None = None,
        basis: Iterable[BasisEntry] = (),
        missing: Iterable[Split] = (),
    ) -> None:
        self.inputs.set(variable, person, value, record_ids, states, uses=uses, basis=basis, missing=missing)

    def exclude(self, person: str, reason: OutOfScopeReason, variable: str | None = None) -> None:
        self.inputs.exclude(person, reason, variable)

    def group(self, name: str, instances: Iterable[GroupInstance]) -> None:
        if name in self.groups:
            raise ValueError(f"グループ {name} を2回書いた")
        self.groups[name] = tuple(instances)


@dataclass(frozen=True)
class StageSpec:
    """段階評価の段（D23 K1・SCOPE §6-3）：前の段の OpenFisca の値と関係から、人をまたぐ関係を決める純粋関数。

    - name：段の名前（登録の全部で一意）。title は人が読む説明。
    - reads：引く変数（OpenFisca の変数名。前の段の値を StageContext.value で読む。宣言していない変数は読めない）。
    - writes：書く入力変数（式のない変数。その段の全員に書く）。概念辞書でその変数の概念に `段階: <name>` を書く。
    - groups：書くグループの複数形（扶養所属一覧など）。グループの概念に `段階: <name>` を書く。組み立てるモジュール（RuleModule.groups）と併用しない。
    - run：StageContext → StageOutput。None なら関数を持たず、build_inputs が YearContext.stage_value(段の名前, 変数, 人) で値を読む段。
      このとき writes は build_inputs が書く入力変数を宣言する（順序と循環の検査に使う）。
    - after：順序を明示したいときの先行する段の名前。
    - basis：この段で書いた入力・グループに付ける根拠（規則の出典）。
    - late_reads：後の段の出力に依存してよい（この段の出力にも依存しうる）値（StageContext.late で読む）。順序の決定には使わない。
      最初は pending の値（変数の既定値）を返す。evaluate は全部の段と最後の計算の後に、段が late で読んだ値を最後の計算の値と比べ、
      違えば最後の計算の値を渡して段を計算し直す（不動点の繰り返し。MAX_FIXPOINT 回まで。収束しなければ pending の値でもう一度
      計算し、段は pending のときの安全側の扱い〔対象外など〕をする）。人ごとに順序が決まる人をまたぐ判定（kyuyo KY-10：
      所得金額調整控除の第1項の「有するか」で回収不能の上限が変わる人）に使う（2026-11-12）。

    順序は宣言から決まる：reads の変数が（宣言した依存をたどって）ほかの段の writes・groups に依存すれば、その段の後。循環は登録の時点で止める。
    """

    name: str
    title: str
    reads: tuple[str, ...]
    writes: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    run: Callable[[StageContext], StageOutput] | None = None
    after: tuple[str, ...] = ()
    basis: tuple[BasisEntry, ...] = ()
    late_reads: tuple[str, ...] = ()


#: 段の late_reads の不動点の繰り返しの上限（evaluate）。
MAX_FIXPOINT = 6


InputBuilder = Callable[["YearContext"], ModuleInputs]
GroupBuilder = Callable[["YearContext"], Iterable[GroupInstance]]
Check = Callable[[CheckContext], Iterable[Exclusion]]
BasisBuilder = Callable[[BasisContext], list[BasisEntry]]


@dataclass(frozen=True)
class RuleModule:
    """規則モジュールの宣言（このファイルの先頭の説明）。name はディレクトリの名前と同じ。"""

    name: str
    title: str
    directory: Path
    variables: tuple[type, ...] = ()
    record_kinds: frozenset[str | RecordKind] = frozenset()
    build_inputs: InputBuilder | None = None
    decisions: tuple[DecisionSpec, ...] = ()
    injections: tuple[InjectionSpec, ...] = ()
    roundings: tuple[RoundingSlotSpec, ...] = ()
    readings: tuple[ReadingSlotSpec, ...] = ()
    groups: Mapping[str, GroupBuilder] = field(default_factory=dict)
    stages: tuple[StageSpec, ...] = ()
    checks: tuple[Check, ...] = ()
    rules: Mapping[str, tuple[BasisEntry, ...]] = field(default_factory=dict)
    rules_by_year: Mapping[int, Mapping[str, tuple[BasisEntry, ...]]] = field(default_factory=dict)
    basis: Mapping[str, BasisBuilder] = field(default_factory=dict)

    @property
    def parameters_dir(self) -> Path:
        return self.directory / "parameters"

    @property
    def data_dir(self) -> Path:
        return self.directory / "data"


# ---------------------------------------------------------------------------
# 年分の状況（モジュールが中間表現を読むときの窓口）
# ---------------------------------------------------------------------------


def heads(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """判断・選択の置き換えの連鎖の先頭（ほかの記録に置き換えられていないもの）。順は元のまま。"""
    items = list(records)
    replaced = {r["replaces"] for r in items if r.get("replaces")}
    return [r for r in items if r["id"] not in replaced]


def overlaps_year(when: Mapping[str, Any] | None, year: int) -> bool:
    """記録・判断の when が年と重なるか。when が無い・年度の形なら、重なるものとして扱う（安全側）。"""
    if not when:
        return True
    start, end = _dt.date(year, 1, 1), _dt.date(year, 12, 31)
    if "on" in when:
        return start <= _dt.date.fromisoformat(when["on"]) <= end
    if "from_on" in when:
        a = _dt.date.fromisoformat(when["from_on"])
        b = _dt.date.fromisoformat(when["to_on"]) if when.get("to_on") else None
        return a <= end and (b is None or b >= start)
    if "tax_year" in when:
        return when["tax_year"] == year
    return True


RECORD_SECTIONS: tuple[str, ...] = (
    "relations",
    "residences",
    "insurance_memberships",
    "facts",
    "assets",
    "filed_documents",
)


@dataclass(frozen=True)
class YearWindow:
    """YearContext の窓口（evaluate が渡す）。テストで YearContext を直接作るときは省略できる（使うと ValueError で知らせる）。"""

    parameters_at: Callable[[str], Any] | None = None
    parameter_root: Any = None
    filing_date: FilingDate | None = None
    rounding: Mapping[str, str] = field(default_factory=dict)  # 端数の名前 → 今の候補の名前
    rounding_reads: set[str] | None = None  # 候補を読んだ端数の名前（evaluate が分かれ目を開く）
    stage_values: Mapping[str, Mapping[tuple[str, str], StageValue]] = field(default_factory=dict)  # 段の名前 → (変数, 人) → 値
    variable_default: Callable[[str], Any] | None = None
    windows: tuple[Window, ...] = ()  # この situation で答える問いの時点（timepoints.Unit.windows）
    injected: Any = None  # 注入データ（injection.InjectedData。None は注入なし）
    lazy_decisions: Mapping[tuple[str, str], str] = field(default_factory=dict)  # 読んだときだけ開く1か所 (種類, key) → 分かれ目の ID
    decision_reads: set[str] | None = None  # 読んだ「読んだときだけ開く1か所」の分かれ目の ID（evaluate が分かれ目を開く）


class YearContext:
    """年分ごとの中間表現の窓口（モジュールの build_inputs・groups・decisions に渡す。段階の関数には StageContext）。

    - persons：その年分に生存している人（生年月日がその年の12月31日以前で、死亡日がその年の1月1日以後）。中間表現の順。
    - records(kind)：記録（relations〜filed_documents）のうち、その種類のもの（年分で絞らない。絞るのはモジュール）。
    - judgments(kind)・choices(kind)：置き換えの連鎖の先頭だけ。
    - decision(kind, key)：判断・選択の1か所の値（Decided）。宣言していない1か所を聞くと KeyError。
    - relations：人をまたぐ関係の窓口（relations.RelationView。親族・婚姻・同居など区間つき）。
    - parameters・parameters_at(日付)・parameter_root・parameter_basis(名前)：パラメータの窓口（build_inputs からパラメータを引く）。
    - rounding_candidate(名前)・round_unfounded(名前, 値)：根拠のない端数の候補（読んだときだけ分かれ目を開く）。
    - filing_date：問いの提出日（予定日。D22 S4。申告期限や施行日をまたぐ版の切替えに使う）。問いになければ None。
    - stage_value(段の名前, 変数, 人)：前の段の値（StageSpec(run=None) の段の reads。最初の段では pending の値）。
    - windows・window(制度, 問い)：この situation で答える問いの時点（timepoints.Window：年度・賦課期日・前年の12月31日・判定日など）。
      year は situation の年（所得の年分）。年度 F の住民税・国保・国年は year＝F−1 の situation で計算する（timepoints の説明）。
    - injection(注入点, key)：注入データの1か所の値（InjectionSpec で宣言したもの。Decided）。injected は注入データの全体。
    """

    def __init__(
        self,
        ir: Mapping[str, Any],
        year: int,
        persons: tuple[str, ...],
        decided: Mapping[tuple[str, str], Decided] | None = None,
        *,
        window: YearWindow | None = None,
    ) -> None:
        self.ir = ir
        self.year = year
        self.persons = persons
        self._decided = dict(decided or {})
        self._people = {p["id"]: p for p in ir["persons"]}
        self._window = window if window is not None else YearWindow()
        self._relations: RelationView | None = None
        #: build_inputs が stage_value で読んだ値（build_year が段の出力の既定の uses にする）。
        self.stage_reads: list[StageValue] = []
        #: 読んだものの記録（build_year の使い回しが使う。None なら記録しない）：判断・選択・注入の1か所と端数・読みの候補。
        self.read_log: list[tuple[str, str, Any]] | None = None
        #: stage_value を呼んだか（pending を含む）。
        self.stage_touched = False
        #: stage_value で読んだ値の記録（situation._reuse が使う。None なら記録しない）：(段の名前, 変数, 人, 返した値)。
        self.stage_log: list[tuple[str, str, str, StageValue]] | None = None

    def person(self, pid: str) -> Mapping[str, Any]:
        return self._people[pid]

    def birth_on(self, pid: str) -> _dt.date:
        return _dt.date.fromisoformat(self._people[pid]["birth_on"])

    def death_on(self, pid: str) -> _dt.date | None:
        d = self._people[pid].get("death_on")
        return _dt.date.fromisoformat(d) if d else None

    def records(self, kind: str) -> list[Mapping[str, Any]]:
        return [r for s in RECORD_SECTIONS for r in self.ir[s] if r["kind"] == kind]

    def judgments(self, kind: str) -> list[Mapping[str, Any]]:
        return heads(j for j in self.ir["judgments"] if j["kind"] == kind)

    def choices(self, kind: str) -> list[Mapping[str, Any]]:
        return heads(c for c in self.ir["choices"] if c["kind"] == kind)

    def decision(self, kind: str, key: str) -> Decided:
        try:
            d = self._decided[(kind, key)]
        except KeyError:
            raise KeyError(f"宣言していない判断・選択の1か所を聞いた: {kind} {key}（DecisionSpec.slots に足す）") from None
        sid = self._window.lazy_decisions.get((kind, key))
        if sid is not None and self._window.decision_reads is not None:
            self._window.decision_reads.add(sid)  # 読んだときだけ開く1か所：読んだので分かれ目を開く
        if self.read_log is not None:
            self.read_log.append((kind, key, d))
        return d

    def with_decided(self, decided: Mapping[tuple[str, str], Decided], *, window: YearWindow | None = None) -> YearContext:
        new = YearContext(self.ir, self.year, self.persons, decided, window=window if window is not None else self._window)
        new._relations = self._relations
        return new

    @property
    def relations(self) -> RelationView:
        if self._relations is None:
            self._relations = RelationView(self.ir)
        return self._relations

    @property
    def filing_date(self) -> FilingDate | None:
        return self._window.filing_date

    @property
    def windows(self) -> tuple[Window, ...]:
        """この situation で答える問いの時点（所得税の年分・年度・判定日）。"""
        return self._window.windows

    def window(self, institution: str, question: str) -> Window | None:
        """制度・問い（年分・年度・判定日）の窓口。この situation で答えないなら None（入力には仮の値を書く）。"""
        for w in self._window.windows:
            if w.institution == institution and w.question == question:
                return w
        return None

    @property
    def injected(self) -> Any:
        """注入データ（injection.InjectedData）。注入がなければ空。"""
        from .injection import EMPTY  # 関数の中で読む（循環を避ける）

        return self._window.injected if self._window.injected is not None else EMPTY

    def injection(self, point: str, key: str) -> Decided:
        """注入データの1か所の値（InjectionSpec.slots が宣言したもの）。宣言していない1か所を聞くと KeyError。"""
        return self.decision(injection_kind(point), key)

    def parameters_at(self, on: _dt.date | str) -> Any:
        """指定の日の ParameterNodeAtInstant（施行日をまたぐ版の切替えなど）。"""
        fn = self._window.parameters_at
        if fn is None:
            raise ValueError("この YearContext にはパラメータの窓口がない（evaluate の外で作ったもの）")
        return fn(on.isoformat() if isinstance(on, _dt.date) else on)

    @property
    def parameters(self) -> Any:
        """その年分の1月1日の ParameterNodeAtInstant（パラメータの適用開始日のキーはその年分の1月1日）。"""
        return self.parameters_at(_dt.date(self.year, 1, 1))

    @property
    def parameter_root(self) -> Any:
        """パラメータの木（ParameterNode。根拠の組み立てに使う）。"""
        if self._window.parameter_root is None:
            raise ValueError("この YearContext にはパラメータの窓口がない（evaluate の外で作ったもの）")
        return self._window.parameter_root

    def parameter_basis(self, name: str, on: _dt.date | str | None = None) -> BasisEntry:
        """パラメータ name の、on（省略ならその年分の1月1日）の値の根拠（InputValue.basis・StageOutput.set の basis に入れる）。"""
        from .explain import parameter_basis as _parameter_basis  # 関数の中で読む（explain は openfisca_core を読む）

        instant = on.isoformat() if isinstance(on, _dt.date) else on or f"{self.year}-01-01"
        return _parameter_basis(self.parameter_root, name, instant)

    def rounding_candidate(self, name: str) -> str:
        """根拠のない端数 name（RoundingSlotSpec.name）の今の候補の名前（floor・ceil・half_up）。読むと分かれ目を開く。"""
        if name not in self._window.rounding:
            raise KeyError(f"宣言していない根拠のない端数: {name}（RoundingSlotSpec を足す）")
        if self._window.rounding_reads is not None:
            self._window.rounding_reads.add(name)
        if self.read_log is not None:
            self.read_log.append(("", name, self._window.rounding[name]))
        return self._window.rounding[name]

    def reading(self, name: str) -> str:
        """法令の読みの候補 name（ReadingSlotSpec.name）の今の候補の名前。読むと分かれ目を開く。"""
        if name not in self._window.rounding:
            raise KeyError(f"宣言していない法令の読みの候補: {name}（ReadingSlotSpec を足す）")
        if self._window.rounding_reads is not None:
            self._window.rounding_reads.add(name)
        if self.read_log is not None:
            self.read_log.append(("", name, self._window.rounding[name]))
        return self._window.rounding[name]

    def round_unfounded(self, name: str, value: Any) -> int:
        """根拠のない端数 name の今の候補で value（Fraction か int）を丸める。"""
        from .rounding import FUNCTIONS  # 関数の中で読む（rounding は candidates を通じて result を読む）

        return FUNCTIONS[self.rounding_candidate(name)](value)

    def stage_value(self, stage: str, variable: str, person: str) -> StageValue:
        """StageSpec(run=None) の段 stage が reads に宣言した変数の、前の段の値。まだ計算していない段では pending の値。"""
        self.stage_touched = True
        values = self._window.stage_values.get(stage)
        if values is None:
            default = self._window.variable_default
            pending = StageValue(variable, person, None if default is None else default(variable), pending=True)
            if self.stage_log is not None:
                self.stage_log.append((stage, variable, person, pending))
            return pending
        try:
            v = values[(variable, person)]
        except KeyError:
            raise KeyError(f"段 {stage} が reads に宣言していない変数か人: {variable} {person}") from None
        self.stage_reads.append(v)
        if self.stage_log is not None:
            self.stage_log.append((stage, variable, person, v))
        return v


class StageContext(YearContext):
    """段階の関数（StageSpec.run）の窓口：YearContext の全部に、前の段の値を引く value・values を足したもの。"""

    def __init__(
        self,
        base: YearContext,
        stage: StageSpec,
        values: Mapping[tuple[str, str], StageValue],
        late: Mapping[tuple[str, str], StageValue] | None = None,
    ) -> None:
        super().__init__(base.ir, base.year, base.persons, base._decided, window=base._window)
        self._relations = base._relations
        self.stage = stage
        self._values = values
        self._late = late or {}
        #: この段で読んだ値（uses を渡さなかった出力の既定の uses）。
        self.reads: list[StageValue] = []
        #: late で読んだ値（evaluate が最後の計算の値と比べる。不動点の繰り返し）。
        self.late_log: list[StageValue] = []

    def late(self, variable: str, person: str) -> StageValue:
        """後の段の出力に依存する値（StageSpec.late_reads）。最初の計算では pending の値（既定値）、繰り返しでは前の最後の計算の値。

        読んだ値は uses に自動では入らない（pending のときは由来がない）。値を使ったら出力の uses に渡す。
        """
        if variable not in self.stage.late_reads:
            raise KeyError(f"段 {self.stage.name} の late_reads にない変数を読んだ: {variable}（StageSpec.late_reads に足す）")
        v = self._late.get((variable, person))
        if v is None:
            default = self._window.variable_default
            v = StageValue(variable, person, None if default is None else default(variable), pending=True)
        self.late_log.append(v)
        return v

    def value(self, variable: str, person: str) -> StageValue:
        """前の段の、person の variable の値（宣言した reads だけ）。ほかの人の値も引ける（人をまたぐ関係のために）。"""
        if variable not in self.stage.reads:
            raise KeyError(f"段 {self.stage.name} の reads にない変数を読んだ: {variable}（StageSpec.reads に足す）")
        v = self._values[(variable, person)]
        self.reads.append(v)
        return v

    def values(self, variable: str) -> dict[str, StageValue]:
        """全員分の値（人 → StageValue）。"""
        return {p: self.value(variable, p) for p in self.persons}


def alive_in_year(person: Mapping[str, Any], year: int) -> bool:
    """その年分に生存している（その年の中に生まれている日がある）か。"""
    birth = _dt.date.fromisoformat(person["birth_on"])
    death = _dt.date.fromisoformat(person["death_on"]) if person.get("death_on") else None
    return birth <= _dt.date(year, 12, 31) and (death is None or death >= _dt.date(year, 1, 1))


# ---------------------------------------------------------------------------
# 登録の一覧から作るもの
# ---------------------------------------------------------------------------


class RegistryError(ValueError):
    """登録の一覧と概念辞書が食い違う。"""

    def __init__(self, problems: Iterable[ConceptProblem]) -> None:
        self.problems = tuple(problems)
        super().__init__("規則モジュールの登録の誤り:\n" + "\n".join(str(p) for p in self.problems))


@dataclass(frozen=True)
class OutputSpec:
    """評価して結果に出す変数（概念辞書の「出力」から作る）。

    - value_type：概念の値の型（円・真偽・整数・区分・日付）。
    - needs_complete_income：その人の全部の所得に依存する（所得の種類ごとの所得の集約点か、それに依存する）。
      どのモジュールも使わない、所得に関係する記録を持つ人では対象外にする（scope.INCOME_RELATED_KINDS）。
    """

    variable: str
    concept: str
    value_type: str
    filing_item: bool
    filing_scope: bool
    needs_complete_income: bool = False


@dataclass(frozen=True)
class StagePlan:
    """段階評価の順序（宣言から導く。D23 K1）。

    - ranks[r]：計算の第 r 回（0 始まり）の値を読む段。第 r+1 回の計算は ranks[0..r] の出力を入れて行う。全部の段の後に最後の計算をする。
    - written_variables・written_groups：run のある段が書く入力変数・グループ → 段の名前。
    - read_specs[r]：第 r 回に読む変数のうち、結果の出力でないもの（値の由来を集めるのに要る）。
    - pending[r]：第 r 回の時点でまだ決まっていない段の出力に依存する変数（計算の後の検出がこれを読んだら、その回の検出は飛ばす）。
    """

    ranks: tuple[tuple[StageSpec, ...], ...] = ()
    written_variables: Mapping[str, str] = field(default_factory=dict)
    written_groups: Mapping[str, str] = field(default_factory=dict)
    read_specs: tuple[tuple[OutputSpec, ...], ...] = ()
    pending: tuple[frozenset[str], ...] = ()
    late_specs: tuple[OutputSpec, ...] = ()  # 段の late_reads の変数（結果の出力でないものも。最後の計算で値を集める）

    @property
    def rounds(self) -> int:
        return len(self.ranks)


@dataclass(frozen=True)
class AgeBoundarySpec:
    """年齢の境目の宣言を変数で引ける形にしたもの（概念辞書の「年齢の境目」。concepts.AgeBoundaryInfo）。"""

    boundary_id: str
    related_variable: str  # 宣言した概念の変数（その値を結果の related に出す）
    age_variable: str  # 比べる年齢の変数
    reference: str  # 判定の日（concepts.AGE_REFERENCE_DAYS）
    criterion: str | None  # 基準のパラメータの葉（比較はメタデータ）
    age_value: int | None  # 基準の年齢の数（criterion がないとき）
    comparison: str | None  # 基準の年齢の比較の向き
    exclude_variable: str | None  # 真なら出さない真偽の変数
    from_param: str | None  # 判定日の下限（ISO の日付を値に持つパラメータの葉）


@dataclass(frozen=True)
class Registry:
    """登録した規則モジュールと概念辞書の組。evaluate と build_system が使う。"""

    modules: tuple[RuleModule, ...]
    dictionary: ConceptDictionary
    outputs: tuple[OutputSpec, ...]
    boundaries: tuple[tuple[str, str, str, str], ...]
    variable_module: Mapping[str, str]
    placeholders: Mapping[str, Concept]
    used_record_kinds: frozenset[str]
    used_decision_kinds: frozenset[str]
    rules: Mapping[str, tuple[BasisEntry, ...]]
    basis_builders: Mapping[str, BasisBuilder]
    stages: StagePlan = field(default_factory=StagePlan)
    whole_record_kinds: frozenset[str] = frozenset()
    record_matchers: tuple[RecordKind, ...] = ()
    rules_by_year: Mapping[int, Mapping[str, tuple[BasisEntry, ...]]] = field(default_factory=dict)
    used_injection_points: frozenset[str] = frozenset()
    age_boundaries: tuple[AgeBoundarySpec, ...] = ()  # 年齢の境目（2026-11-12）

    def available_questions(self) -> frozenset[tuple[str, str]]:
        """結果に出す概念の（制度, 問い）の組（timepoints.plan_units の available）。"""
        return frozenset(
            (c.institution, c.timing.question) for o in self.outputs if (c := self.dictionary.get(o.concept)) is not None
        )

    def module(self, name: str) -> RuleModule:
        for m in self.modules:
            if m.name == name:
                return m
        raise KeyError(name)

    def uses_record(self, rec: Mapping[str, Any]) -> bool:
        """中間表現の記録を、どれかのモジュールが使うか（record_kinds の宣言。種類より細かい宣言 RecordKind を含む）。"""
        return rec["kind"] in self.whole_record_kinds or any(m.matches(rec) for m in self.record_matchers)

    def rules_for(self, variable: str, year: int) -> tuple[BasisEntry, ...]:
        """変数のパラメータでない規則の根拠：全部の年分のもの（rules）と、その年分のもの（rules_by_year）。"""
        return tuple(self.rules.get(variable, ())) + tuple(self.rules_by_year.get(year, {}).get(variable, ()))

    def input_variables(self, module: RuleModule) -> tuple[str, ...]:
        """モジュールの入力変数（式のない変数）の名前（プロセスで1回だけ求める）。"""
        cache = memo(self, "input_variables")
        key = module.name
        if key not in cache:
            cache[key] = tuple(v.__name__ for v in module.variables if not _has_formula(v))
        return cache[key]


def memo(obj: Any, name: str) -> dict[Any, Any]:
    """変わらないオブジェクト（frozen の Registry・ConceptDictionary など）に付ける、名前ごとの使い回しの表。

    登録・概念辞書・パラメータの木は作った後に変えないので、そこから導くもの（依存の閉包・入力変数の一覧・版のハッシュなど）は
    プロセスで1回だけ求める。frozen の dataclass でも __dict__ に直接書く（属性の検査を通らない）。
    """
    store = obj.__dict__.setdefault("_okura_memo", {})
    return store.setdefault(name, {})


def _has_formula(cls: type) -> bool:
    return any(name.startswith("formula") and callable(getattr(cls, name)) for name in dir(cls))


def build_registry(modules: Iterable[RuleModule], *, extra_module_dirs: Iterable[Path] = ()) -> Registry:
    """登録の一覧から Registry を作る。辞書との食い違いがあれば RegistryError（import の時点で止める）。"""
    mods = tuple(modules)
    problems: list[ConceptProblem] = []
    add = lambda code, where, msg: problems.append(ConceptProblem(code, where, msg))  # noqa: E731
    names = [m.name for m in mods]
    if len(set(names)) != len(names):
        add("duplicate_module", ",".join(names), "同じ名前のモジュールを2回登録している")
    dirs = list(default_module_dirs())
    for m in mods:
        if m.directory.name != m.name:
            add("module_directory", m.name, f"ディレクトリの名前 {m.directory.name} がモジュールの名前と違う")
        if m.directory not in dirs:
            dirs.append(m.directory)
    for extra in extra_module_dirs:
        if extra not in dirs:
            dirs.append(extra)
    d = load_dictionary(module_dirs=tuple(dirs))
    registered = set(names)
    var_module: dict[str, str] = {}
    for m in mods:
        for v in m.variables:
            n = v.__name__
            if n in var_module:
                add("duplicate_variable", n, f"変数が {var_module[n]} と {m.name} の両方にある")
            var_module[n] = m.name
            c = d.by_variable(n)
            if c is None:
                add("unregistered_variable", n, "概念辞書のどの概念にも対応しない")
                continue
            if c.module != m.name:
                add("module_mismatch", n, f"概念 {c.id} の担当は {c.module}（変数は {m.name} にある）")
            if not c.implemented:
                add("stale_not_implemented", n, f"変数があるのに {c.id} が実装済みでない")
        for spec in m.roundings:
            if spec.variable is not None and spec.variable not in {v.__name__ for v in m.variables}:
                add("rounding_variable", m.name, f"端数の候補を渡す変数 {spec.variable} がこのモジュールの変数にない")
        for rspec in m.readings:
            if rspec.variable is not None and rspec.variable not in {v.__name__ for v in m.variables}:
                add("reading_variable", m.name, f"読みの候補を渡す変数 {rspec.variable} がこのモジュールの変数にない")
            if len(rspec.candidates) < 2 or len(set(rspec.candidates)) != len(rspec.candidates):
                add("reading_candidates", m.name, f"読みの候補 {rspec.name} は重複のない2つ以上の名前が要る")
            if any(r.name == rspec.name for r in m.roundings):
                add("reading_name", m.name, f"読みの候補 {rspec.name} の名前が根拠のない端数と同じ")
        for ispec in m.injections:
            if ispec.point not in _points():
                add("unknown_injection_point", m.name, f"注入点 {ispec.point} が injection_points.POINTS にない")
            elif not any(ispec.point in c.injection_data for c in d.concepts if c.module == m.name):
                add("undeclared_injection_point", m.name, f"注入点 {ispec.point} をこのモジュールの概念の「注入データ」に書いていない")
        for g in m.groups:
            for other in mods:
                if other is not m and g in other.groups:
                    add("duplicate_group", g, f"グループ {g} を {m.name} と {other.name} の両方が組み立てる")
    placeholders: dict[str, Concept] = {}
    for c in d.concepts:
        if c.module is None:
            continue
        if c.implemented:
            if c.module not in registered:
                add("implemented_not_registered", c.id, f"実装済みなのに担当のモジュール {c.module} が登録されていない（rules/__init__.py）")
            for v in c.variables:
                if v not in var_module:
                    add("implemented_but_missing", c.id, f"実装済みなのに変数 {v} がどのモジュールにもない")
        else:
            for v in c.variables:
                if v in var_module:
                    continue
                placeholders[v] = c
    outputs = tuple(
        OutputSpec(
            variable=c.variables[0],
            concept=c.id,
            value_type=c.value_type,
            filing_item=c.output.filing_item,
            filing_scope=c.output.filing_scope,
            needs_complete_income=d.depends_on_all_income(c.id),
        )
        for c in d.outputs()
        if c.output is not None and c.variables and c.variables[0] in var_module
    )
    # 境目：(判定の変数, 比べる変数, 基準のパラメータの葉か基準の変数, 境目の ID, 基準の比較〔基準が変数のときだけ。パラメータなら None〕)
    boundaries = tuple(
        (
            c.variables[0],
            d.concept(b.compared).variables[0],
            d.concept(b.criterion).variables[0] if b.criterion_is_concept else b.criterion,
            b.id,
            b.comparison if b.criterion_is_concept else None,
        )
        for c in d.outputs()
        if c.variables and c.variables[0] in var_module
        for b in c.boundaries
    )
    # 年齢の境目（2026-11-12）：比べる年齢・除く条件の概念も登録したモジュールの出力であること
    age_boundaries: list[AgeBoundarySpec] = []
    for c in d.outputs():
        if not (c.variables and c.variables[0] in var_module):
            continue
        for ab in c.age_boundaries:
            age_c, ex_c = d.get(ab.age), (d.get(ab.exclude) if ab.exclude else None)
            if age_c is None or not age_c.variables or age_c.variables[0] not in var_module:
                add("age_boundary", c.id, f"年齢の境目 {ab.id} の比べる年齢 {ab.age} が登録したモジュールの変数でない")
                continue
            if ab.exclude and (ex_c is None or not ex_c.variables or ex_c.variables[0] not in var_module):
                add("age_boundary", c.id, f"年齢の境目 {ab.id} の除く条件 {ab.exclude} が登録したモジュールの変数でない")
                continue
            age_boundaries.append(
                AgeBoundarySpec(
                    boundary_id=ab.id,
                    related_variable=c.variables[0],
                    age_variable=age_c.variables[0],
                    reference=ab.reference,
                    criterion=ab.criterion,
                    age_value=ab.age_value,
                    comparison=ab.comparison,
                    exclude_variable=ex_c.variables[0] if ex_c is not None else None,
                    from_param=ab.from_param,
                )
            )
    rules: dict[str, tuple[BasisEntry, ...]] = {}
    by_year: dict[int, dict[str, tuple[BasisEntry, ...]]] = {}
    basis: dict[str, BasisBuilder] = {}
    for m in mods:
        for k, v in m.rules.items():
            if var_module.get(k) != m.name:
                add("rules_variable", m.name, f"規則の根拠の変数 {k} がこのモジュールの変数でない")
            rules[k] = tuple(v)
        for y, table in m.rules_by_year.items():
            for k, v in table.items():
                if var_module.get(k) != m.name:
                    add("rules_variable", m.name, f"年分別の規則の根拠の変数 {k} がこのモジュールの変数でない")
                by_year.setdefault(y, {})[k] = tuple(v)
        for k, b in m.basis.items():
            if var_module.get(k) != m.name:
                add("basis_variable", m.name, f"根拠の組み立ての変数 {k} がこのモジュールの変数でない")
            basis[k] = b
    plan = _plan_stages(mods, d, outputs, var_module, add)
    if problems:
        raise RegistryError(problems)
    return Registry(
        modules=mods,
        dictionary=d,
        outputs=outputs,
        boundaries=boundaries,
        variable_module=MappingProxyType(var_module),
        placeholders=MappingProxyType(placeholders),
        used_record_kinds=frozenset(k if isinstance(k, str) else k.kind for m in mods for k in m.record_kinds),
        used_decision_kinds=frozenset(s.kind for m in mods for s in m.decisions),
        rules=MappingProxyType(rules),
        basis_builders=MappingProxyType(basis),
        stages=plan,
        whole_record_kinds=frozenset(k for m in mods for k in m.record_kinds if isinstance(k, str)),
        record_matchers=tuple(k for m in mods for k in m.record_kinds if not isinstance(k, str)),
        rules_by_year=MappingProxyType({y: MappingProxyType(t) for y, t in by_year.items()}),
        used_injection_points=frozenset(s.point for m in mods for s in m.injections),
        age_boundaries=tuple(age_boundaries),
    )


def _points() -> Mapping[str, Any]:
    from .injection_points import POINTS  # 関数の中で読む（循環を避ける）

    return POINTS


def _stage_closure(d: ConceptDictionary, concept_id: str, collected_into: Mapping[str, tuple[str, ...]]) -> set[str]:
    """concept_id と、宣言した依存（と集約点が「集める先」から集める概念）をたどって届く概念の ID。"""
    seen: set[str] = set()
    stack = [concept_id]
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        c = d.get(cid)
        if c is None:
            continue
        seen.add(cid)
        stack.extend(c.declared_targets())
        stack.extend(collected_into.get(cid, ()))
    return seen


def _plan_stages(
    mods: tuple[RuleModule, ...],
    d: ConceptDictionary,
    outputs: tuple[OutputSpec, ...],
    var_module: Mapping[str, str],
    add: Callable[[str, str, str], None],
) -> StagePlan:
    """段の宣言を検査し、順序（StagePlan）を作る。循環は stage_cycle で止める（D23 K1）。"""
    specs = [(m, s) for m in mods for s in m.stages]
    names = [s.name for _, s in specs]
    for n in sorted({n for n in names if names.count(n) > 1}):
        add("stage_duplicate", n, "同じ名前の段が2つある")
    known_stages = set(names)
    group_key = {e.plural: e.key for e in ENTITIES if not e.is_person}
    writer_var: dict[str, str] = {}
    writer_group: dict[str, str] = {}
    run_vars: dict[str, str] = {}
    run_groups: dict[str, str] = {}
    module_of_stage: dict[str, RuleModule] = {}
    for m, s in specs:
        module_of_stage[s.name] = m
        own = {v.__name__: v for v in m.variables}
        for v in s.writes:
            if v not in own:
                add("stage_write", s.name, f"書く変数 {v} がこのモジュールの変数にない")
                continue
            if _has_formula(own[v]):
                add("stage_write", s.name, f"書く変数 {v} に式がある（入力変数だけを書ける）")
            if v in writer_var:
                add("stage_write_twice", v, f"段 {writer_var[v]} と {s.name} の両方が書く")
            writer_var[v] = s.name
            if s.run is not None:
                run_vars[v] = s.name
            concept = d.by_variable(v)
            if concept is None or concept.stage != s.name:
                add("stage_concept", s.name, f"変数 {v} の概念に `段階: {s.name}` がない（概念辞書に記録する：SCOPE §6-3）")
            elif concept.entity in group_key.values():
                add("stage_write", s.name, f"書く変数 {v} が人の変数でない（段階は人ごとに書く）")
        for g in s.groups:
            if g not in group_key:
                add("stage_group", s.name, f"知らないグループ: {g}")
                continue
            if g in writer_group:
                add("stage_write_twice", g, f"段 {writer_group[g]} と {s.name} の両方が書く")
            writer_group[g] = s.name
            if s.run is not None:
                run_groups[g] = s.name
            for other in mods:
                if g in other.groups:
                    add("stage_group", s.name, f"グループ {g} をモジュール {other.name} も組み立てる（どちらか一方）")
            group_concepts = [c for c in d.concepts if c.entity == group_key[g]]
            if not any(c.stage == s.name for c in group_concepts):
                add("stage_concept", s.name, f"グループ {g} の概念に `段階: {s.name}` がない（概念辞書に記録する：SCOPE §6-3）")
        if s.groups and s.run is None:
            add("stage_group", s.name, "グループを書く段は run が要る")
        for v in (*s.reads, *s.late_reads):
            c = d.by_variable(v)
            if c is None:
                add("stage_read", s.name, f"読む変数 {v} が概念辞書にない")
            elif c.entity in group_key.values():
                add("stage_read", s.name, f"読む変数 {v} が人の変数でない（段階は人ごとの値を読む）")
        if s.late_reads and s.run is None:
            add("stage_read", s.name, "late_reads は run のある段だけ（build_inputs の段は読めない）")
        for a in s.after:
            if a not in known_stages:
                add("stage_after", s.name, f"after の段 {a} がない")
    for c in d.concepts:
        if c.stage is not None and c.module in {m.name for m in mods} and c.stage not in known_stages:
            add("stage_concept", c.id, f"概念の `段階: {c.stage}` に対応する段がない")
    if not specs:
        return StagePlan()
    collected_into: dict[str, list[str]] = {}
    for k in d.concepts:
        for target in k.collected_by:
            collected_into.setdefault(target, []).append(k.id)
    written_concepts: dict[str, str] = {}
    for v, stage in writer_var.items():
        c = d.by_variable(v)
        if c is not None:
            written_concepts[c.id] = stage
    for c in d.concepts:
        for plural, key in group_key.items():
            if c.entity == key and plural in writer_group:
                written_concepts[c.id] = writer_group[plural]
    deps: dict[str, set[str]] = {s.name: set(s.after) for _, s in specs}
    for _, s in specs:
        for v in s.reads:
            c = d.by_variable(v)
            if c is None:
                continue
            for cid in _stage_closure(d, c.id, collected_into):
                if cid in written_concepts:
                    deps[s.name].add(written_concepts[cid])
    order = [s.name for _, s in specs]
    rank: dict[str, int] = {}
    remaining = set(order)
    while remaining:
        ready = [n for n in order if n in remaining and deps[n] <= set(rank)]
        if not ready:
            add("stage_cycle", ",".join(sorted(remaining)), "段の間の依存が循環している（reads の変数がほかの段の出力に依存し、その段が先の段の出力に依存する）")
            return StagePlan()
        for n in ready:
            rank[n] = 1 + max((rank[x] for x in deps[n]), default=-1)
        remaining -= set(ready)
    count = 1 + max(rank.values())
    by_name = {s.name: s for _, s in specs}
    ranks = tuple(tuple(by_name[n] for n in order if rank[n] == r) for r in range(count))
    outputs_by_var = {o.variable: o for o in outputs}
    read_specs: list[tuple[OutputSpec, ...]] = []
    for r in range(count):
        seen: dict[str, OutputSpec] = {}
        for s in ranks[r]:
            for v in s.reads:
                c = d.by_variable(v)
                if v in outputs_by_var or v in seen or c is None:
                    continue
                seen[v] = OutputSpec(v, c.id, c.value_type, False, False, d.depends_on_all_income(c.id))
        read_specs.append(tuple(seen.values()))
    closures = {c.id: _stage_closure(d, c.id, collected_into) for c in d.concepts}
    pending: list[frozenset[str]] = []
    for r in range(count):
        stages_pending = {n for n in order if rank[n] >= r}
        pending_concepts = {cid for cid, st in written_concepts.items() if st in stages_pending}
        pending.append(frozenset(v for c in d.concepts if closures[c.id] & pending_concepts for v in c.variables))
    late: dict[str, OutputSpec] = {}
    for _, s in specs:
        for v in s.late_reads:
            c = d.by_variable(v)
            if c is None or v in late:
                continue
            late[v] = outputs_by_var.get(v) or OutputSpec(v, c.id, c.value_type, False, False, d.depends_on_all_income(c.id))
    return StagePlan(
        ranks=ranks,
        written_variables=MappingProxyType(run_vars),
        written_groups=MappingProxyType(run_groups),
        read_specs=tuple(read_specs),
        pending=tuple(pending),
        late_specs=tuple(late.values()),
    )


_DEFAULT: list[Registry] = []


def default_registry() -> Registry:
    """rules/__init__.py に登録したモジュールの Registry（最初に呼んだときに作り、同じものを返す。不変の値）。"""
    if not _DEFAULT:
        from .rules import MODULES  # 循環を避けるため関数の中で読む（rules のモジュールは country.entities を読む）

        _DEFAULT.append(build_registry(MODULES))
    return _DEFAULT[0]


__all__ = [
    "AgeBoundarySpec",
    "BasisBuilder",
    "BasisContext",
    "Check",
    "CheckContext",
    "Decided",
    "DecisionSlot",
    "DecisionSpec",
    "Exclusion",
    "InjectionSlot",
    "InjectionSpec",
    "injection_key",
    "injection_kind",
    "unique_splits",
    "StageContext",
    "StageOutput",
    "StagePlan",
    "StageSpec",
    "StageValue",
    "YearWindow",
    "RecordKind",
    "GroupBuilder",
    "GroupInstance",
    "InputBuilder",
    "InputValue",
    "ModuleInputs",
    "OutputSpec",
    "RECORD_SECTIONS",
    "Registry",
    "RegistryError",
    "ReadingSlotSpec",
    "RoundingSlotSpec",
    "RuleModule",
    "YearContext",
    "alive_in_year",
    "build_registry",
    "default_registry",
    "heads",
    "overlaps_year",
]

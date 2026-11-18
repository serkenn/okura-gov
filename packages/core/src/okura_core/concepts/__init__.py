"""概念辞書（SCOPE §6・§7）：法令の概念の一覧の読み込みと、構造の検査。

置き場所：
  - この包みの structure.yaml：層（順位つき）と制度（概念 ID の接頭辞・変数の接頭辞・依存してよい制度）。共通の部分。
  - この包みのそれ以外の *.yaml：まだ規則モジュールを持たない制度の概念（住民税・国保・国年・健保）。先頭に `制度:`、`概念:`。
  - 規則モジュールの rules/<名前>/concepts.yaml：そのモジュールが担当する概念（未実装の約束を含む）。先頭に `制度:`・`担当: <名前>`
    （ディレクトリの名前と同じ）・`概念:`。モジュールは自分の concepts.yaml だけを直す。

概念の項目（キーは日本語。知らないキーは誤り）：
  id                  `<制度>.<名前>`（例 所得税.合計所得金額）。同じ言葉で意味が違うものは別の ID にする（SCOPE §7）
  名称                人が読む名前
  定義                {条文, 根拠の種類（basis.SourceKind の名前）, 出典（docs のファイル#節のリスト）}
  判定の時点          {問い（年分・年度・判定日）, 説明, 出典}
  層                  structure.yaml の層の id
  エンティティ        OpenFisca のエンティティのキー（未実装なら予定の名前でよい）
  期間                OpenFisca の変数の定義の期間：年・月・日・永久（変数の definition_period と照らす）
  値の型              円（整数の円）・真偽・整数・区分（文字列）・日付
  依存する概念        （省略可・既定は空）同じ制度の概念 ID のリスト（式が引く概念を全部書く）
  制度をまたぐ依存    （省略可）[{概念, 説明, 出典}]。依存してよい制度へだけ
  人をまたぐ依存      （省略可）[{概念, 説明, 出典}]。上の2つで宣言した概念のうち、ほかの人の値を使うもの
  年をまたぐ依存      （省略可）[{概念 か パラメータ, 時点, 説明, 出典}]。ほかの年分・年度の値を使うもの
  集約点              （省略可）集める層の id。その層へ上の層から直接つないでよいのは集約点だけ（SCOPE §6-4）
  集約点を通らない依存（省略可）[{概念, 説明, 出典}]。集約点でない概念が、集約点のある層を直接引く例外
  変数                OpenFisca の変数名のリスト（未実装なら予定の名前）
  パラメータ          （省略可）使うパラメータの名前（木の節を書けば、その下の葉の全部）
  注入点              （省略可・既定は false）市町村・保険者ごとに注入されるデータか（true ならパラメータを持たない）
  注入データ          （省略可）この概念の値が使う注入点の名前のリスト（injection_points.POINTS。D17・D19）。
                      注入点の制度は、概念の制度か「依存してよい制度」。規則モジュールの InjectionSpec はここに書いた注入点だけを使える
  実装済み            OpenFisca の変数が担当のモジュールにあるか。false の変数は「仮置きの変数」（registry・build_system）
  未実装のとき        （省略可）{零とする記録の種類: [中間表現の kind], 説明}。未実装の間、その人にこれらの記録が年分に
                      なければ値は0とみなしてよい（仮置きの変数の0を使う）。書かなければ、仮置きの変数に依存する値は対象外
  集める先            （省略可）この概念を集める集約点の概念 ID のリスト。集約点が依存する概念に入れていないものは、
                      その人の値が0でなければ集約点を対象外にする（集め忘れを黙って通さない）
  段階                （省略可）この概念の入力変数・グループを書く段階評価の段の名前（registry.StageSpec。D23 K1・SCOPE §6-3）。
                      段階で書く入力変数は事実の層に置く（式を持たず、依存を持たない。材料の依存は StageSpec.reads に宣言する）
  出力                （省略可）{申告の欄, 申告の範囲}。evaluate が結果に出す値（Registry.outputs）
  境目                （省略可）[{id, 比べる概念, 基準（パラメータ名）}] か [{id, 比べる概念, 基準の概念, 比較}]。境目の説明（Registry.boundaries）。
                      基準の概念（2026-11-11）：基準が判定日・年齢・制度などで変わり、パラメータの葉1つで書けないときに、基準の額を値に持つ
                      概念（円の出力）を書く。比較は「以下・未満・超・以上」。基準の概念は依存する概念に書く
  年齢の境目          （省略可。2026-11-12）[{id, 比べる年齢, 判定の日, 基準（パラメータ名）か 基準の年齢と比較, 除く条件?, 判定日の下限?}]。
                      判定の日（AGE_REFERENCE_DAYS）の終了時の年齢と基準の年齢の比較の境目（生年月日・境目の日・あと何日。Registry.age_boundaries）。
                      比べる年齢は同じ制度の整数の出力、除く条件は真偽の出力（真なら出さない）、判定日の下限は ISO の日付を値に持つパラメータの葉。
                      出力を持つ概念に付ける（判定の概念でなくてよい。年齢の比較だけを説明する）
  注                  （省略可）
判定の時点は {問い, 説明, 出典} か、問いの名前だけ（年分・年度・判定日。説明は既定、出典は定義の出典）でもよい。
規則モジュールのファイルは先頭に `既定:`（エンティティ・期間・値の型・判定の時点・注入点・実装済み・層）を書ける。項目の値が優先。

読み込みは PyYAML の安全な読み込み（SafeLoader。python のタグは誤り）に、重複したキーを誤りにする検査を足したもの。

検査（どれも純粋関数。結果は ConceptProblem のリスト）：
  check_dictionary(辞書)            辞書の中の矛盾。load_dictionary は矛盾があれば ConceptDictionaryError を投げる
  check_variables(辞書, 変数の情報)  OpenFisca の変数と辞書の対応（未登録・接頭辞・エンティティ・期間・型）
  check_edges(辞書, 変数の依存)      式の依存と辞書の宣言（層の逆向き・循環・宣言のない依存・制度・人・年をまたぐ依存・集約点）
  check_parameters(辞書, 葉の名前)   パラメータの葉と辞書の対応
  check_parameter_use(辞書, 使用)    式が使ったパラメータと辞書の宣言
  check_group_uses(辞書, 使用)       式がグループの組み方（人.<グループ>…・has_role）を使うなら、グループの概念への依存の宣言
変数の依存は tests/test_architecture.py が式の AST と OpenFisca のトレースから作って渡す。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ..basis import INJECTION_ONLY_KINDS, SourceKind

CONCEPTS_DIR = Path(__file__).resolve().parent
STRUCTURE_FILE = "structure.yaml"

#: 事実（入力変数）の層。依存を持たない。
FACT_LAYER = "事実"
#: 「その人の全部の所得に依存する」かの判定に使う層（この層の集約点に依存する値）。
INCOME_LAYER = "所得の種類ごとの所得"
#: 中心の概念の層（所得金額調整控除・合計所得金額など）。
CENTRAL_LAYER = "中心の概念"
#: 判定の時点の問い（SCOPE §8、design-vocabulary N7）。
QUESTIONS: tuple[str, ...] = ("年分", "年度", "判定日")
#: 問い → OpenFisca の変数の定義の期間（制約があるものだけ）。
#: situation は暦年（所得の年分）ごとに作るので、年度・判定日の概念の変数も年の期間（timepoints の説明）。
QUESTION_PERIODS: Mapping[str, frozenset[str]] = {
    "年分": frozenset({"year"}),
    "年度": frozenset({"year"}),
    "判定日": frozenset({"year"}),
}
#: 期間 → OpenFisca の definition_period。
PERIODS: Mapping[str, str] = {"年": "year", "月": "month", "日": "day", "永久": "eternity"}
#: 値の型 → OpenFisca の変数の value_type の名前。
VALUE_TYPES: Mapping[str, str] = {"円": "int", "真偽": "bool", "整数": "int", "区分": "str", "日付": "date"}
#: 規則モジュールのディレクトリ（rules/<名前>/concepts.yaml）。
RULES_DIR = CONCEPTS_DIR.parent / "rules"
MODULE_CONCEPTS_FILE = "concepts.yaml"
#: 出典に書いてよい場所（一次情報：公開資料の情報と実測）。
_REFERENCE = re.compile(r"^docs/(public-sources|measurements)/[^#\s]+\.md(#[^\s#]+)?$")


# ---------------------------------------------------------------------------
# 問題と誤り
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptProblem:
    """検査で見つかった問題。code は機械が読む短い名前、where は概念 ID・変数名・ファイルなど。"""

    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.where}: {self.message}"


class ConceptDictionaryError(ValueError):
    """概念辞書が読めない・矛盾している。"""

    def __init__(self, problems: Iterable[ConceptProblem]) -> None:
        self.problems = tuple(problems)
        super().__init__("概念辞書の誤り:\n" + "\n".join(str(p) for p in self.problems))


# ---------------------------------------------------------------------------
# 型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layer:
    id: str
    rank: int
    description: str


@dataclass(frozen=True)
class Institution:
    id: str
    variable_prefix: str
    may_depend_on: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class Definition:
    law: str
    source_kind: SourceKind
    references: tuple[str, ...]


@dataclass(frozen=True)
class Timing:
    question: str
    description: str
    references: tuple[str, ...]


@dataclass(frozen=True)
class DeclaredDependency:
    """宣言した依存の1項目。is_parameter は年をまたぐ依存でパラメータを指すとき。"""

    target: str
    is_parameter: bool
    description: str | None
    when: str | None
    references: tuple[str, ...]


@dataclass(frozen=True)
class OutputInfo:
    filing_item: bool
    filing_scope: bool


@dataclass(frozen=True)
class Unimplemented:
    """未実装の間の扱い：zero_record_kinds の記録がその人・年分になければ、仮置きの変数の0を使ってよい。"""

    zero_record_kinds: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class BoundaryInfo:
    id: str
    compared: str
    criterion: str  # パラメータの葉の名前か、基準の概念の ID（criterion_is_concept）
    criterion_is_concept: bool = False
    comparison: str | None = None  # 基準の概念のときの比較の向き（以下・未満・超・以上）


#: 年齢の境目の判定の日（年齢はその日の終了時の年齢：年齢計算ニ関スル法律・民法第143条）。値は evaluate が評価の単位と中間表現から求める。
#: 「その年」は situation の年（所得の年分）。「判定日」は判定日の単位の判定日。
AGE_REFERENCE_DAYS: tuple[str, ...] = (
    "その年12月31日",
    "その年12月31日（死亡の時はその前日）",
    "判定日",
    "判定日の属する年の12月31日",
)


@dataclass(frozen=True)
class AgeBoundaryInfo:
    """年齢の境目の宣言（2026-11-12）：判定の日の終了時の年齢と基準の年齢の比較（例「12月31日に19歳以上か」）。

    age は比べる年齢（整数の出力を持つ概念。規則モジュールが計算した年齢と、生年月日と判定の日から求めた年齢が同じときだけ出す）。
    基準はパラメータの葉（criterion。比較の向きはメタデータ）か、年齢の数（age_value と comparison。根拠は宣言した概念の定義）。
    exclude は真のとき出さない真偽の概念（判定の日が別の日になる人：所得税の判定する人の判定の時など）。
    from_param は判定日がこの日（パラメータの葉の値。ISO の日付の文字列）より前なら出さない（区分の適用開始日）。
    """

    id: str
    age: str
    reference: str
    criterion: str | None = None
    age_value: int | None = None
    comparison: str | None = None
    exclude: str | None = None
    from_param: str | None = None


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    institution: str
    definition: Definition
    timing: Timing
    layer: str
    entity: str
    period: str
    value_type: str
    depends_on: tuple[str, ...]
    cross_institution: tuple[DeclaredDependency, ...]
    cross_person: tuple[DeclaredDependency, ...]
    cross_year: tuple[DeclaredDependency, ...]
    aggregates: str | None
    bypasses_aggregation: tuple[DeclaredDependency, ...]
    variables: tuple[str, ...]
    parameters: tuple[str, ...]
    injection_point: bool
    implemented: bool
    output: OutputInfo | None
    boundaries: tuple[BoundaryInfo, ...]
    note: str | None
    source_file: str
    module: str | None = None
    unimplemented: Unimplemented | None = None
    collected_by: tuple[str, ...] = ()
    stage: str | None = None
    injection_data: tuple[str, ...] = ()
    age_boundaries: tuple[AgeBoundaryInfo, ...] = ()

    def declared_targets(self) -> tuple[str, ...]:
        """式が引いてよい概念（同じ制度の依存と、制度をまたぐ依存）。"""
        return self.depends_on + tuple(d.target for d in self.cross_institution)

    def references(self) -> tuple[str, ...]:
        """この項目の出典の全部（定義・判定の時点・宣言した依存）。"""
        out = list(self.definition.references) + list(self.timing.references)
        for deps in (self.cross_institution, self.cross_person, self.cross_year, self.bypasses_aggregation):
            for d in deps:
                out += d.references
        return tuple(out)


@dataclass(frozen=True)
class ConceptDictionary:
    layers: tuple[Layer, ...]
    institutions: tuple[Institution, ...]
    concepts: tuple[Concept, ...]
    _by_id: Mapping[str, Concept] = field(init=False, repr=False, compare=False)
    _by_variable: Mapping[str, Concept] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_id: dict[str, Concept] = {}
        by_var: dict[str, Concept] = {}
        for c in self.concepts:
            by_id.setdefault(c.id, c)
            for v in c.variables:
                by_var.setdefault(v, c)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))
        object.__setattr__(self, "_by_variable", MappingProxyType(by_var))

    # --- 参照 ---

    def concept(self, concept_id: str) -> Concept:
        return self._by_id[concept_id]

    def get(self, concept_id: str) -> Concept | None:
        return self._by_id.get(concept_id)

    def by_variable(self, variable: str) -> Concept | None:
        return self._by_variable.get(variable)

    def layer(self, layer_id: str) -> Layer | None:
        return next((x for x in self.layers if x.id == layer_id), None)

    def institution(self, institution_id: str) -> Institution | None:
        return next((x for x in self.institutions if x.id == institution_id), None)

    def rank(self, concept_id: str) -> int:
        layer = self.layer(self.concept(concept_id).layer)
        if layer is None:
            raise KeyError(f"層がない: {concept_id}")
        return layer.rank

    def institution_of_variable_name(self, variable: str) -> Institution | None:
        """変数名の接頭辞から制度を引く（一番長い接頭辞）。"""
        hits = [i for i in self.institutions if variable.startswith(i.variable_prefix)]
        return max(hits, key=lambda i: len(i.variable_prefix)) if hits else None

    def ids(self) -> frozenset[str]:
        """結果に出てよい ID：概念 ID と境目の ID。"""
        return frozenset(c.id for c in self.concepts) | frozenset(b.id for c in self.concepts for b in c.boundaries)

    def aggregated_layers(self) -> frozenset[str]:
        return frozenset(c.aggregates for c in self.concepts if c.aggregates)

    # --- 導くもの ---

    def topological_order(self) -> tuple[Concept, ...]:
        """宣言した依存の順（依存先が先）。同じ順位では辞書の順。循環があれば ConceptDictionaryError。"""
        index = {c.id: i for i, c in enumerate(self.concepts)}
        deps = {c.id: [t for t in c.declared_targets() if t in index] for c in self.concepts}
        done: list[str] = []
        placed: set[str] = set()
        while len(done) < len(self.concepts):
            ready = [c.id for c in self.concepts if c.id not in placed and all(t in placed for t in deps[c.id])]
            if not ready:
                rest = sorted(set(index) - placed, key=index.__getitem__)
                raise ConceptDictionaryError([ConceptProblem("cycle", ", ".join(rest), "宣言した依存が循環している")])
            first = min(ready, key=index.__getitem__)
            done.append(first)
            placed.add(first)
        return tuple(self.concept(x) for x in done)

    def outputs(self) -> tuple[Concept, ...]:
        """evaluate が結果に出す概念（実装済み・出力あり）を、依存の順に。"""
        return tuple(c for c in self.topological_order() if c.implemented and c.output is not None)

    def closure(self, concept_id: str) -> tuple[Concept, ...]:
        """concept_id と、宣言した依存をたどって届く概念の全部（辞書の順）。辞書は変わらないので、概念ごとに1回だけ求める。"""
        cache = self.__dict__.setdefault("_closure_cache", {})
        hit = cache.get(concept_id)
        if hit is not None:
            return hit
        cache[concept_id] = out = self._closure(concept_id)
        return out

    def _closure(self, concept_id: str) -> tuple[Concept, ...]:
        seen: set[str] = set()
        stack = [concept_id]
        while stack:
            cid = stack.pop()
            if cid in seen or cid not in self._by_id:
                continue
            seen.add(cid)
            stack.extend(self._by_id[cid].declared_targets())
        return tuple(c for c in self.concepts if c.id in seen)

    def depends_on_all_income(self, concept_id: str) -> bool:
        """その人の全部の所得に依存するか（所得の種類ごとの所得の集約点か、それに依存する）。"""
        return any(c.aggregates == INCOME_LAYER for c in self.closure(concept_id))


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------


class _StrictSafeLoader(yaml.SafeLoader):
    """重複したキーを誤りにする安全な読み込み（SafeLoader の部分クラス。SafeLoader 自体は変えない）。"""


def _construct_mapping(loader: _StrictSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"重複したキー: {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def read_yaml(text: str, name: str) -> Any:
    """YAML の文字列を安全に読む（タグ・重複したキーは ConceptDictionaryError）。"""
    try:
        return yaml.load(text, Loader=_StrictSafeLoader)  # noqa: S506（安全な読み込みの部分クラス）
    except yaml.YAMLError as e:
        raise ConceptDictionaryError([ConceptProblem("yaml", name, str(e))]) from None


class _Reader:
    """形の検査をしながら値を取り出す（問題は集めて、最後にまとめて返す）。"""

    def __init__(self, data: Any, where: str, problems: list[ConceptProblem]) -> None:
        self.where = where
        self.problems = problems
        if not isinstance(data, Mapping):
            problems.append(ConceptProblem("shape", where, "対応表（mapping）でない"))
            data = {}
        self.data: Mapping[str, Any] = data
        self.used: set[str] = set()

    def _bad(self, key: str, message: str) -> None:
        self.problems.append(ConceptProblem("shape", f"{self.where}.{key}", message))

    def raw(self, key: str, required: bool = True) -> Any:
        self.used.add(key)
        if key not in self.data:
            if required:
                self._bad(key, "必須のキーがない")
            return None
        return self.data[key]

    def text(self, key: str, required: bool = True) -> str | None:
        v = self.raw(key, required)
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            self._bad(key, "空でない文字列でない")
            return None
        return v

    def flag(self, key: str, required: bool = True) -> bool:
        v = self.raw(key, required)
        if v is None and not required:
            return False
        if not isinstance(v, bool):
            if v is not None:
                self._bad(key, "true・false でない")
            return False
        return v

    def texts(self, key: str, required: bool = True) -> tuple[str, ...]:
        v = self.raw(key, required)
        if v is None:
            return ()
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            self._bad(key, "空でない文字列のリストでない")
            return ()
        return tuple(v)

    def items(self, key: str) -> list[Any]:
        v = self.raw(key, required=False)
        if v is None:
            return []
        if not isinstance(v, list):
            self._bad(key, "リストでない")
            return []
        return v

    def finish(self) -> None:
        for key in sorted(set(self.data) - self.used, key=str):
            self._bad(str(key), "知らないキー")


def _dependency(data: Any, where: str, problems: list[ConceptProblem], allow_parameter: bool) -> DeclaredDependency | None:
    r = _Reader(data, where, problems)
    concept = r.text("概念", required=False)
    parameter = r.text("パラメータ", required=False) if allow_parameter else None
    description = r.text("説明", required=False)
    when = r.text("時点", required=allow_parameter)
    refs = r.texts("出典")
    r.finish()
    if (concept is None) == (parameter is None):
        problems.append(ConceptProblem("shape", where, "「概念」か「パラメータ」のどちらか1つを書く" if allow_parameter else "「概念」がない"))
        return None
    if not refs:
        problems.append(ConceptProblem("shape", where, "出典がない"))
    target = concept if concept is not None else parameter
    assert target is not None
    return DeclaredDependency(target, parameter is not None, description, when, refs)


def _dependencies(r: _Reader, key: str, problems: list[ConceptProblem], allow_parameter: bool = False) -> tuple[DeclaredDependency, ...]:
    out = []
    for i, item in enumerate(r.items(key)):
        d = _dependency(item, f"{r.where}.{key}[{i}]", problems, allow_parameter)
        if d is not None:
            out.append(d)
    return tuple(out)


#: ファイルの先頭の「既定」に書けるキー（概念の項目に同じキーがあれば項目の値を使う）。
_DEFAULTABLE = frozenset({"エンティティ", "期間", "値の型", "判定の時点", "注入点", "実装済み", "層"})

_TIMING_DEFAULT = {"年分": "その年分の値", "年度": "その年度の値", "判定日": "判定日の値"}


def _concept(
    data: Any, where: str, institution: str, source_file: str, problems: list[ConceptProblem], module: str | None = None
) -> Concept | None:
    r = _Reader(data, where, problems)
    cid = r.text("id")
    if cid is not None:
        r.where = where = f"{source_file}:{cid}"
    name = r.text("名称")

    d = _Reader(r.raw("定義"), f"{where}.定義", problems)
    law = d.text("条文")
    kind_label = d.text("根拠の種類")
    def_refs = d.texts("出典")
    d.finish()
    kind: SourceKind | None = None
    if kind_label is not None:
        try:
            kind = SourceKind.from_label(kind_label)
        except ValueError as e:
            problems.append(ConceptProblem("shape", f"{where}.定義.根拠の種類", str(e)))

    raw_timing = r.raw("判定の時点")
    if isinstance(raw_timing, str):  # 省略形：問いの名前だけ（説明は既定、出典は定義の出典）
        question: str | None = raw_timing
        timing_text: str | None = _TIMING_DEFAULT.get(raw_timing, raw_timing)
        timing_refs = def_refs
    else:
        t = _Reader(raw_timing, f"{where}.判定の時点", problems)
        question = t.text("問い")
        timing_text = t.text("説明")
        timing_refs = t.texts("出典")
        t.finish()

    layer = r.text("層")
    entity = r.text("エンティティ")
    period = r.text("期間")
    value_type = r.text("値の型")
    depends_on = r.texts("依存する概念", required=False)
    cross_institution = _dependencies(r, "制度をまたぐ依存", problems)
    cross_person = _dependencies(r, "人をまたぐ依存", problems)
    cross_year = _dependencies(r, "年をまたぐ依存", problems, allow_parameter=True)
    aggregates = r.text("集約点", required=False)
    bypasses = _dependencies(r, "集約点を通らない依存", problems)
    variables = r.texts("変数")
    parameters = r.texts("パラメータ", required=False)
    injection = r.flag("注入点", required=False)
    injection_data = r.texts("注入データ", required=False)
    implemented = r.flag("実装済み")

    unimplemented: Unimplemented | None = None
    raw_unimpl = r.raw("未実装のとき", required=False)
    if raw_unimpl is not None:
        u = _Reader(raw_unimpl, f"{where}.未実装のとき", problems)
        kinds = u.texts("零とする記録の種類")
        desc = u.text("説明")
        u.finish()
        unimplemented = Unimplemented(kinds, desc or "")
    collected_by = r.texts("集める先", required=False)
    stage = r.text("段階", required=False)

    output: OutputInfo | None = None
    raw_output = r.raw("出力", required=False)
    if raw_output is not None:
        o = _Reader(raw_output, f"{where}.出力", problems)
        output = OutputInfo(o.flag("申告の欄"), o.flag("申告の範囲"))
        o.finish()

    boundaries = []
    for i, item in enumerate(r.items("境目")):
        b = _Reader(item, f"{where}.境目[{i}]", problems)
        bid, compared = b.text("id"), b.text("比べる概念")
        criterion = b.text("基準", required=False)
        criterion_concept = b.text("基準の概念", required=False)
        comparison = b.text("比較", required=False)
        b.finish()
        if (criterion is None) == (criterion_concept is None):
            problems.append(ConceptProblem("shape", f"{where}.境目[{i}]", "「基準」（パラメータ）か「基準の概念」のどちらか1つを書く"))
        elif criterion_concept is not None and comparison is None:
            problems.append(ConceptProblem("shape", f"{where}.境目[{i}]", "「基準の概念」には「比較」を書く"))
        elif criterion is not None and comparison is not None:
            problems.append(ConceptProblem("shape", f"{where}.境目[{i}]", "「比較」は「基準の概念」のときだけ（パラメータの比較はメタデータ）"))
        elif bid and compared:
            if criterion is not None:
                boundaries.append(BoundaryInfo(bid, compared, criterion))
            else:
                boundaries.append(BoundaryInfo(bid, compared, criterion_concept or "", True, comparison))
    age_boundaries = []
    for i, item in enumerate(r.items("年齢の境目")):
        at = f"{where}.年齢の境目[{i}]"
        b = _Reader(item, at, problems)
        bid, age, reference = b.text("id"), b.text("比べる年齢"), b.text("判定の日")
        criterion = b.text("基準", required=False)
        age_value = b.raw("基準の年齢", required=False)
        comparison = b.text("比較", required=False)
        exclude = b.text("除く条件", required=False)
        from_param = b.text("判定日の下限", required=False)
        b.finish()
        if (criterion is None) == (age_value is None):
            problems.append(ConceptProblem("shape", at, "「基準」（パラメータ）か「基準の年齢」のどちらか1つを書く"))
        elif age_value is not None and (type(age_value) is not int or age_value < 0):
            problems.append(ConceptProblem("shape", at, "「基準の年齢」は0以上の整数"))
        elif age_value is not None and comparison is None:
            problems.append(ConceptProblem("shape", at, "「基準の年齢」には「比較」を書く"))
        elif criterion is not None and comparison is not None:
            problems.append(ConceptProblem("shape", at, "「比較」は「基準の年齢」のときだけ（パラメータの比較はメタデータ）"))
        elif reference is not None and reference not in AGE_REFERENCE_DAYS:
            problems.append(ConceptProblem("shape", at, f"「判定の日」は {'・'.join(AGE_REFERENCE_DAYS)} のどれか: {reference}"))
        elif bid and age and reference:
            age_boundaries.append(AgeBoundaryInfo(bid, age, reference, criterion, age_value, comparison, exclude, from_param))
    note = r.text("注", required=False)
    r.finish()

    if None in (cid, name, law, kind, question, timing_text, layer, entity, period, value_type):
        return None
    assert cid and name and law and kind and question and timing_text and layer and entity and period and value_type
    return Concept(
        id=cid,
        name=name,
        institution=institution,
        definition=Definition(law, kind, def_refs),
        timing=Timing(question, timing_text, timing_refs),
        layer=layer,
        entity=entity,
        period=period,
        value_type=value_type,
        depends_on=depends_on,
        cross_institution=cross_institution,
        cross_person=cross_person,
        cross_year=cross_year,
        aggregates=aggregates,
        bypasses_aggregation=bypasses,
        variables=variables,
        parameters=parameters,
        injection_point=injection,
        injection_data=injection_data,
        implemented=implemented,
        output=output,
        boundaries=tuple(boundaries),
        age_boundaries=tuple(age_boundaries),
        note=note,
        source_file=source_file,
        module=module,
        unimplemented=unimplemented,
        collected_by=collected_by,
        stage=stage,
    )


def parse_dictionary(structure: Any, files: Mapping[str, Any]) -> ConceptDictionary:
    """読んだ YAML（structure と、ファイル名 → 制度ごとの内容）から辞書を作る。形の誤りは ConceptDictionaryError。

    ファイル名が "rules/<名前>/concepts.yaml" の形なら規則モジュールのファイルで、先頭の `担当:` が <名前> と同じこと。
    概念の並びは、structure の制度の順、同じ制度ではファイル名の順、ファイルの中の順。
    """
    problems: list[ConceptProblem] = []
    s = _Reader(structure, STRUCTURE_FILE, problems)
    layers: list[Layer] = []
    for i, item in enumerate(s.items("層")):
        r = _Reader(item, f"{STRUCTURE_FILE}.層[{i}]", problems)
        lid, rank, desc = r.text("id"), r.raw("順位"), r.text("説明")
        r.finish()
        if not isinstance(rank, int) or isinstance(rank, bool):
            problems.append(ConceptProblem("shape", f"{STRUCTURE_FILE}.層[{i}].順位", "整数でない"))
            continue
        if lid and desc:
            layers.append(Layer(lid, rank, desc))
    institutions: list[Institution] = []
    for i, item in enumerate(s.items("制度")):
        r = _Reader(item, f"{STRUCTURE_FILE}.制度[{i}]", problems)
        iid, prefix, deps, desc = r.text("id"), r.text("変数の接頭辞"), r.texts("依存してよい制度"), r.text("説明")
        r.finish()
        if iid and prefix and desc:
            institutions.append(Institution(iid, prefix, deps, desc))
    s.finish()

    order = {inst.id: i for i, inst in enumerate(institutions)}
    per_file: list[tuple[int, str, list[Concept]]] = []
    for fname in sorted(files):
        f = _Reader(files[fname], fname, problems)
        inst = f.text("制度")
        module_dir = _module_of_file(fname)
        module = f.text("担当", required=module_dir is not None)
        raw_concepts = f.items("概念")
        defaults = f.raw("既定", required=False)
        f.finish()
        if defaults is not None and (
            not isinstance(defaults, Mapping) or set(defaults) - _DEFAULTABLE
        ):
            problems.append(ConceptProblem("shape", f"{fname}.既定", f"既定に書けるキーは {sorted(_DEFAULTABLE)}"))
            defaults = None
        if module_dir is None and module is not None:
            problems.append(ConceptProblem("module", fname, "担当は規則モジュールのファイル（rules/<名前>/concepts.yaml）にだけ書く"))
        if module_dir is not None and module is not None and module != module_dir:
            problems.append(ConceptProblem("module", fname, f"担当 {module} がディレクトリの名前 {module_dir} と違う"))
        if inst is None:
            continue
        if inst not in order:
            problems.append(ConceptProblem("unknown_institution", fname, f"structure.yaml にない制度: {inst}"))
            continue
        concepts = []
        for i, item in enumerate(raw_concepts):
            if defaults and isinstance(item, Mapping):
                item = {**defaults, **item}
            c = _concept(item, f"{fname}.概念[{i}]", inst, fname, problems, module)
            if c is not None:
                concepts.append(c)
        per_file.append((order[inst], fname, concepts))
    if problems:
        raise ConceptDictionaryError(problems)
    ordered = tuple(c for _, _, cs in sorted(per_file, key=lambda x: (x[0], x[1])) for c in cs)
    return ConceptDictionary(tuple(layers), tuple(institutions), ordered)


def _module_of_file(fname: str) -> str | None:
    parts = fname.split("/")
    if len(parts) == 3 and parts[0] == "rules" and parts[2] == MODULE_CONCEPTS_FILE:
        return parts[1]
    return None


def default_module_dirs() -> tuple[Path, ...]:
    """rules/ の下で concepts.yaml を持つディレクトリ（名前の順）。登録していない雛形のモジュールも含む（約束を読むため）。"""
    if not RULES_DIR.is_dir():
        return ()
    return tuple(p for p in sorted(RULES_DIR.iterdir()) if (p / MODULE_CONCEPTS_FILE).is_file())


def read_files(directory: Path = CONCEPTS_DIR, module_dirs: Iterable[Path] | None = None) -> tuple[Any, dict[str, Any]]:
    """YAML を読む（structure.yaml と、それ以外の *.yaml と、規則モジュールの concepts.yaml）。

    規則モジュールのファイルの名前は "rules/<ディレクトリの名前>/concepts.yaml"。
    """
    structure = read_yaml((directory / STRUCTURE_FILE).read_text(encoding="utf-8"), STRUCTURE_FILE)
    files = {
        p.name: read_yaml(p.read_text(encoding="utf-8"), p.name)
        for p in sorted(directory.glob("*.yaml"))
        if p.name != STRUCTURE_FILE
    }
    for mdir in default_module_dirs() if module_dirs is None else module_dirs:
        f = mdir / MODULE_CONCEPTS_FILE
        if not f.is_file():
            continue
        name = f"rules/{mdir.name}/{MODULE_CONCEPTS_FILE}"
        if name in files:
            raise ConceptDictionaryError([ConceptProblem("module", name, "同じ名前のモジュールのディレクトリが2つある")])
        files[name] = read_yaml(f.read_text(encoding="utf-8"), name)
    return structure, files


def load_dictionary(module_dirs: Iterable[Path] | None = None) -> ConceptDictionary:
    """概念辞書を読み、check_dictionary で検査して返す（矛盾があれば ConceptDictionaryError）。

    module_dirs は規則モジュールのディレクトリ（None なら rules/ の下の全部）。
    返す値は不変（frozen dataclass・タプル・読み取り専用の対応表）。呼ぶたびにファイルを読む（キャッシュを持たない）。
    """
    structure, files = read_files(module_dirs=module_dirs)
    d = parse_dictionary(structure, files)
    problems = check_dictionary(d)
    if problems:
        raise ConceptDictionaryError(problems)
    return d


# ---------------------------------------------------------------------------
# 検査：辞書の中
# ---------------------------------------------------------------------------


def _covers(declared: str, parameter: str) -> bool:
    """declared（節か葉の名前）が parameter（葉の名前）を含むか。"""
    return parameter == declared or parameter.startswith(declared + ".")


def _find_cycles(graph: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """強連結成分のうち循環になっているもの（2つ以上、又は自己ループ）。決定的な順。"""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: list[list[str]] = []
    counter = [0]
    nodes = sorted(set(graph) | {t for ts in graph.values() for t in ts})
    succ = {n: sorted(set(graph.get(n, ()))) for n in nodes}

    def strong(v: str) -> None:
        # 再帰の深さは変数・概念の数で抑えられる（数百まで）。
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in succ[v]:
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in succ[v]:
                out.append(sorted(comp))

    for n in nodes:
        if n not in index:
            strong(n)
    return sorted(out)


def _ir_record_kinds() -> frozenset[str]:
    """中間表現の記録の種類（okura_ir の語彙。判断・選択は含まない）。"""
    from okura_ir import vocabulary

    return frozenset(k.kind for kinds in vocabulary.RECORD_SECTIONS.values() for k in kinds)


def _injection_points() -> Mapping[str, Any]:
    """注入点の一覧（injection_points.POINTS。関数の中で読む：循環を避ける）。"""
    from ..injection_points import POINTS

    return POINTS


def check_dictionary(d: ConceptDictionary) -> list[ConceptProblem]:
    """辞書の中の矛盾を返す（空なら問題なし）。docs のファイルの実在はテストで確かめる。"""
    p: list[ConceptProblem] = []
    add = lambda code, where, msg: p.append(ConceptProblem(code, where, msg))  # noqa: E731

    # 層と制度
    if len({x.id for x in d.layers}) != len(d.layers) or len({x.rank for x in d.layers}) != len(d.layers):
        add("structure", STRUCTURE_FILE, "層の id・順位が重複している")
    if d.layer(FACT_LAYER) is None or d.layer(INCOME_LAYER) is None:
        add("structure", STRUCTURE_FILE, f"層「{FACT_LAYER}」「{INCOME_LAYER}」がない")
    elif d.layer(FACT_LAYER).rank != min(x.rank for x in d.layers):  # type: ignore[union-attr]
        add("structure", STRUCTURE_FILE, f"層「{FACT_LAYER}」が一番下でない")
    inst_ids = [x.id for x in d.institutions]
    if len(set(inst_ids)) != len(inst_ids):
        add("structure", STRUCTURE_FILE, "制度の id が重複している")
    prefixes = [x.variable_prefix for x in d.institutions]
    if len(set(prefixes)) != len(prefixes):
        add("structure", STRUCTURE_FILE, "変数の接頭辞が重複している")
    for inst in d.institutions:
        if not inst.variable_prefix.endswith("_"):
            add("structure", inst.id, "変数の接頭辞は「_」で終える")
        for other in inst.may_depend_on:
            if other not in inst_ids or other == inst.id:
                add("structure", inst.id, f"依存してよい制度が不正: {other}")
    for cyc in _find_cycles({i.id: i.may_depend_on for i in d.institutions}):
        add("cycle", STRUCTURE_FILE, f"制度の依存が循環している: {' → '.join(cyc)}")

    # 概念
    seen: dict[str, str] = {}
    var_owner: dict[str, str] = {}
    boundary_ids: set[str] = set()
    concept_ids = {c.id for c in d.concepts}
    agg_layers = d.aggregated_layers()
    for c in d.concepts:
        w = c.id
        if c.id in seen:
            add("duplicate_id", w, f"同じ ID が {seen[c.id]} にもある")
        seen.setdefault(c.id, c.source_file)
        if c.id.split(".", 1)[0] != c.institution or "." not in c.id:
            add("prefix_mismatch", w, f"概念 ID の接頭辞が制度（{c.institution}）と違う")
        layer = d.layer(c.layer)
        if layer is None:
            add("unknown_layer", w, f"知らない層: {c.layer}")
            continue
        if c.timing.question not in QUESTIONS:
            add("unknown_question", w, f"判定の時点の問いが {QUESTIONS} のどれでもない: {c.timing.question}")
        if c.period not in PERIODS:
            add("period", w, f"期間が {tuple(PERIODS)} のどれでもない: {c.period}")
        elif c.timing.question in QUESTION_PERIODS and PERIODS[c.period] not in QUESTION_PERIODS[c.timing.question]:
            add("period", w, f"問い「{c.timing.question}」の概念の期間は {sorted(QUESTION_PERIODS[c.timing.question])}")
        if c.value_type not in VALUE_TYPES:
            add("value_type", w, f"値の型が {tuple(VALUE_TYPES)} のどれでもない: {c.value_type}")
        if c.unimplemented is not None:
            if c.implemented:
                add("unimplemented", w, "実装済みの概念に「未実装のとき」を書いている（消す）")
            unknown = [k for k in c.unimplemented.zero_record_kinds if k not in _ir_record_kinds()]
            if unknown:
                add("unimplemented", w, f"中間表現にない記録の種類: {unknown}")
        for target in c.collected_by:
            t = d.get(target)
            if t is None or t.aggregates is None:
                add("collected_by", w, f"集める先 {target} が集約点の概念でない")
            elif t.institution != c.institution:
                add("collected_by", w, f"集める先 {target} が別の制度")
        if c.definition.source_kind in INJECTION_ONLY_KINDS:
            add("source_kind", w, "自治体の資料は注入データの出典にだけ使う（D22 S2）")
        for ref in c.references():
            if not _REFERENCE.match(ref):
                add("reference_format", w, f"出典は docs/public-sources か docs/measurements の .md（#節）: {ref}")
        inst = d.institution(c.institution)
        if inst is None:
            add("unknown_institution", w, f"知らない制度: {c.institution}")
            continue
        # 変数
        if c.implemented and not c.variables:
            add("implemented_without_variable", w, "実装済みなのに変数がない")
        for v in c.variables:
            if not v.startswith(inst.variable_prefix):
                add("variable_prefix", w, f"変数 {v} の接頭辞が制度の「{inst.variable_prefix}」でない")
            if v in var_owner:
                add("duplicate_variable", w, f"変数 {v} が {var_owner[v]} にもある")
            var_owner.setdefault(v, c.id)
        # パラメータ・注入点
        for name in c.injection_data:
            point = _injection_points().get(name)
            if point is None:
                add("unknown_injection_point", w, f"注入データの注入点 {name} が injection_points.POINTS にない")
            elif point.institution != c.institution and point.institution not in inst.may_depend_on:
                add("injection_institution", w, f"注入点 {name} の制度 {point.institution} は、この概念の制度か依存してよい制度でない")
        if c.injection_point and c.parameters:
            add("injection_with_parameters", w, "注入点はパラメータを持たない（値は注入データから来る）")
        for name in c.parameters:
            if name.split(".", 1)[0] != c.institution:
                add("parameter_root", w, f"パラメータ {name} の木の根が制度（{c.institution}）と違う")
        # 出力・境目
        if c.output is not None and len(c.variables) != 1:
            add("output", w, "出力は、変数が1つの概念にだけ付ける")
        for b in c.boundaries:
            if b.id in concept_ids or b.id in boundary_ids:
                add("boundary", w, f"境目の ID が重複している: {b.id}")
            boundary_ids.add(b.id)
            if b.id.split(".", 1)[0] != c.institution:
                add("boundary", w, f"境目の ID の接頭辞が制度と違う: {b.id}")
            if c.output is None or c.value_type != "真偽":
                add("boundary", w, "境目は真偽の判定の概念に付ける")
            compared = d.get(b.compared)
            if compared is None or compared.output is None or compared.value_type != "円":
                add("boundary", w, f"比べる概念は円の出力を持つ概念: {b.compared}")
            elif c.implemented and not compared.implemented:
                add("boundary", w, f"実装済みの判定の比べる概念が未実装: {b.compared}")
            if b.criterion_is_concept:
                crit = d.get(b.criterion)
                if crit is None or crit.output is None or crit.value_type != "円":
                    add("boundary", w, f"基準の概念は円の出力を持つ概念: {b.criterion}")
                elif b.criterion not in c.depends_on:
                    add("boundary", w, f"基準の概念 {b.criterion} を依存する概念に書いていない")
                if b.comparison not in ("以下", "未満", "超", "以上"):
                    add("boundary", w, f"比較は「以下・未満・超・以上」のどれか: {b.comparison}")
            elif not any(_covers(x, b.criterion) for x in c.parameters):
                add("boundary", w, f"基準 {b.criterion} がこの概念のパラメータにない")
        for ab in c.age_boundaries:  # 年齢の境目（2026-11-12）
            if ab.id in concept_ids or ab.id in boundary_ids:
                add("boundary", w, f"境目の ID が重複している: {ab.id}")
            boundary_ids.add(ab.id)
            if ab.id.split(".", 1)[0] != c.institution:
                add("boundary", w, f"境目の ID の接頭辞が制度と違う: {ab.id}")
            if c.output is None:
                add("boundary", w, "年齢の境目は出力を持つ概念に付ける")
            age = d.get(ab.age)
            if age is None or age.output is None or age.value_type != "整数":
                add("boundary", w, f"比べる年齢は整数の出力を持つ概念: {ab.age}")
            elif age.institution != c.institution:
                add("boundary", w, f"比べる年齢は同じ制度の概念: {ab.age}")
            if ab.exclude is not None:
                ex = d.get(ab.exclude)
                if ex is None or ex.output is None or ex.value_type != "真偽":
                    add("boundary", w, f"除く条件は真偽の出力を持つ概念: {ab.exclude}")
            for name in (ab.criterion, ab.from_param):
                if name is not None and name.split(".", 1)[0] != c.institution:
                    add("boundary", w, f"年齢の境目のパラメータ {name} の木の根が制度（{c.institution}）と違う")
            if ab.age_value is not None and ab.comparison not in ("以下", "未満", "超", "以上"):
                add("boundary", w, f"比較は「以下・未満・超・以上」のどれか: {ab.comparison}")
            if ab.age_value is not None and not c.definition.references:
                add("boundary", w, "基準の年齢の根拠は概念の定義の出典（定義に出典を書く）")
        # 依存
        if c.layer == FACT_LAYER and (c.declared_targets() or c.cross_year or c.cross_person):
            add("fact_with_dependencies", w, "事実の層の概念は依存を持たない")
        if c.aggregates is not None:
            agg = d.layer(c.aggregates)
            if agg is None or agg.rank >= layer.rank:
                add("aggregation_layer", w, f"集約点が集める層は、自分より下の層: {c.aggregates}")
        for t in c.depends_on:
            target = d.get(t)
            if target is None:
                add("unknown_concept", w, f"依存する概念が辞書にない: {t}")
            elif target.institution != c.institution:
                add("cross_institution_in_depends_on", w, f"{t} は別の制度。制度をまたぐ依存に書く")
        for dep in c.cross_institution:
            target = d.get(dep.target)
            if target is None:
                add("unknown_concept", w, f"制度をまたぐ依存の概念が辞書にない: {dep.target}")
            elif target.institution == c.institution:
                add("same_institution_in_cross", w, f"{dep.target} は同じ制度。依存する概念に書く")
            elif target.institution not in inst.may_depend_on:
                add("direction", w, f"{c.institution} は {target.institution} に依存してよい制度でない（structure.yaml）")
        declared = set(c.declared_targets())
        for key, deps in (("人をまたぐ依存", c.cross_person), ("年をまたぐ依存", c.cross_year), ("集約点を通らない依存", c.bypasses_aggregation)):
            for dep in deps:
                if dep.is_parameter:
                    if not any(_covers(x, dep.target) for x in c.parameters):
                        add("qualifier_not_declared", w, f"{key}のパラメータ {dep.target} がこの概念のパラメータにない")
                elif dep.target not in declared:
                    add("qualifier_not_declared", w, f"{key}の {dep.target} が依存する概念・制度をまたぐ依存にない")
        bypass = {x.target for x in c.bypasses_aggregation}
        for t in c.declared_targets():
            target = d.get(t)
            if target is None or d.layer(target.layer) is None:
                continue
            t_rank = d.layer(target.layer).rank  # type: ignore[union-attr]
            if t_rank > layer.rank:
                add("layer_order", w, f"上の層の概念に依存している: {t}（{target.layer}）")
            if target.layer in agg_layers and t_rank < layer.rank and c.aggregates != target.layer and t not in bypass:
                add("bypass_aggregation", w, f"{target.layer}の {t} を集約点を通らずに引いている")
    for cyc in _find_cycles({c.id: c.declared_targets() for c in d.concepts}):
        add("cycle", " → ".join(cyc), "宣言した依存が循環している")
    return p


# ---------------------------------------------------------------------------
# 検査：OpenFisca の変数・式の依存・パラメータ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VariableInfo:
    """OpenFisca の変数の、検査に使う情報（テストが TaxBenefitSystem から作る）。"""

    name: str
    entity: str
    is_person: bool
    has_formula: bool
    period: str  # definition_period（year・month・day・eternity）
    value_type: str  # value_type の名前（int・bool・float・str・date・Enum）
    placeholder: bool = False  # 未実装の概念の仮置きの変数（registry が作る入力変数）
    module: str | None = None  # 変数を持つ規則モジュール（仮置きなら None）


@dataclass(frozen=True)
class VariableEdge:
    """式の依存：source の式が target を引く。cross_person はほかの人（グループ）経由、cross_year は別の期間。"""

    source: str
    target: str
    cross_person: bool = False
    cross_year: bool = False


@dataclass(frozen=True)
class ParameterUse:
    """式が使ったパラメータ（葉の名前）。cross_year は変数の期間と違う時点で引いたとき。"""

    variable: str
    parameter: str
    cross_year: bool = False


def check_variables(d: ConceptDictionary, variables: Iterable[VariableInfo]) -> list[ConceptProblem]:
    """OpenFisca の全変数が辞書に対応し、接頭辞・制度・エンティティ・期間・型が合うか。"""
    p: list[ConceptProblem] = []
    present = {v.name: v for v in variables}
    for v in present.values():
        c = d.by_variable(v.name)
        inst = d.institution_of_variable_name(v.name)
        if inst is None:
            p.append(ConceptProblem("variable_prefix", v.name, "制度の接頭辞（structure.yaml）で始まらない"))
        if v.value_type == "float":
            p.append(ConceptProblem("float", v.name, "float の変数は置かない（金額は整数の円、途中の値は Fraction。D21 R5）"))
        if c is None:
            p.append(ConceptProblem("unregistered_variable", v.name, "概念辞書のどの概念にも対応しない"))
            continue
        if inst is not None and inst.id != c.institution:
            p.append(ConceptProblem("prefix_mismatch", v.name, f"変数の接頭辞の制度（{inst.id}）と概念の制度（{c.institution}）が違う"))
        if v.placeholder:
            if c.implemented:
                p.append(ConceptProblem("placeholder_for_implemented", v.name, f"{c.id} は実装済みなのに仮置きの変数"))
            if v.has_formula:
                p.append(ConceptProblem("placeholder_with_formula", v.name, "仮置きの変数は式を持たない"))
        elif not c.implemented:
            p.append(ConceptProblem("stale_not_implemented", v.name, f"変数があるのに {c.id} が実装済みでない"))
        elif c.module is not None and v.module is not None and v.module != c.module:
            p.append(ConceptProblem("module_mismatch", v.name, f"{c.id} の担当は {c.module}（変数は {v.module} にある）"))
        if v.entity != c.entity:
            p.append(ConceptProblem("entity", v.name, f"エンティティ {v.entity} が辞書（{c.entity}）と違う"))
        allowed = QUESTION_PERIODS.get(c.timing.question)
        if allowed is not None and v.period not in allowed:
            p.append(ConceptProblem("period", v.name, f"問い「{c.timing.question}」の変数の期間は {sorted(allowed)}（今 {v.period}）"))
        if PERIODS.get(c.period) != v.period:
            p.append(ConceptProblem("period", v.name, f"概念の期間 {c.period} と変数の期間 {v.period} が合わない"))
        if VALUE_TYPES.get(c.value_type) != v.value_type:
            p.append(ConceptProblem("value_type", v.name, f"概念の値の型 {c.value_type} と変数の型 {v.value_type} が合わない"))
        if c.layer == FACT_LAYER and v.has_formula:
            p.append(ConceptProblem("fact_with_formula", v.name, "事実の層の変数は式を持たない（入力変数）"))
        if c.layer != FACT_LAYER and not v.has_formula and not v.placeholder:
            p.append(ConceptProblem("formula_missing", v.name, "事実の層でない変数に式がない"))
    for c in d.concepts:
        if c.implemented:
            for name in c.variables:
                if name not in present:
                    p.append(ConceptProblem("implemented_but_missing", c.id, f"実装済みなのに変数 {name} がない"))
    return p


def check_edges(d: ConceptDictionary, edges: Iterable[VariableEdge]) -> list[ConceptProblem]:
    """式の依存を辞書の宣言と照らす：宣言のない依存・制度・人・年をまたぐ依存、層の逆向き、集約点、循環、使っていない宣言。"""
    p: list[ConceptProblem] = []
    edges = list(edges)
    agg_layers = d.aggregated_layers()
    used: set[tuple[str, str]] = set()
    used_person: set[tuple[str, str]] = set()
    used_year: set[tuple[str, str]] = set()
    for e in edges:
        s, t = d.by_variable(e.source), d.by_variable(e.target)
        if s is None or t is None:
            continue  # 未登録は check_variables が出す
        used.add((s.id, t.id))
        if e.cross_person:
            used_person.add((s.id, t.id))
        if e.cross_year:
            used_year.add((s.id, t.id))
        if s.id == t.id:
            continue
        where = f"{e.source} → {e.target}"
        if s.institution == t.institution:
            if t.id not in s.depends_on:
                p.append(ConceptProblem("undeclared_dependency", where, f"{s.id} の依存する概念に {t.id} がない"))
        else:
            if t.id not in {x.target for x in s.cross_institution}:
                p.append(ConceptProblem("undeclared_cross_institution", where, f"{s.id} の制度をまたぐ依存に {t.id} がない"))
            inst = d.institution(s.institution)
            if inst is not None and t.institution not in inst.may_depend_on:
                p.append(ConceptProblem("direction", where, f"{s.institution} は {t.institution} に依存してよい制度でない"))
        s_rank, t_rank = d.rank(s.id), d.rank(t.id)
        if t_rank > s_rank:
            p.append(ConceptProblem("layer_order", where, f"層の逆向き：{s.layer}（{s_rank}）が {t.layer}（{t_rank}）を引く"))
        if (
            t.layer in agg_layers
            and t_rank < s_rank
            and s.aggregates != t.layer
            and t.id not in {x.target for x in s.bypasses_aggregation}
        ):
            p.append(ConceptProblem("bypass_aggregation", where, f"{t.layer}を集約点を通らずに引いている"))
        if e.cross_person and t.id not in {x.target for x in s.cross_person}:
            p.append(ConceptProblem("undeclared_cross_person", where, f"{s.id} の人をまたぐ依存に {t.id} がない"))
        if e.cross_year and t.id not in {x.target for x in s.cross_year if not x.is_parameter}:
            p.append(ConceptProblem("undeclared_cross_year", where, f"{s.id} の年をまたぐ依存に {t.id} がない"))
    for cyc in _find_cycles(_group(edges)):
        p.append(ConceptProblem("cycle", " → ".join(cyc), "変数の依存が循環している"))
    # 宣言だけあって式で使っていない依存（両方が実装済みのとき）
    for c in d.concepts:
        if not c.implemented:
            continue
        for t in c.declared_targets():
            target = d.get(t)
            if target is not None and target.implemented and target.variables and (c.id, t) not in used:
                p.append(ConceptProblem("unused_declaration", c.id, f"宣言した依存 {t} を式で使っていない"))
        for key, deps, seen in (("人をまたぐ依存", c.cross_person, used_person), ("年をまたぐ依存", c.cross_year, used_year)):
            for dep in deps:
                target = d.get(dep.target)
                if not dep.is_parameter and target is not None and target.implemented and (c.id, dep.target) not in seen:
                    p.append(ConceptProblem("unused_declaration", c.id, f"{key} {dep.target} を式で使っていない"))
    return p


@dataclass(frozen=True)
class GroupUse:
    """式がグループ（エンティティのキー）の組み方を使う：人.<グループ>…（射影・集約）・人.has_role(<グループ>.<役割>)。"""

    variable: str
    group: str


def check_group_uses(d: ConceptDictionary, uses: Iterable[GroupUse]) -> list[ConceptProblem]:
    """グループの組み方を使う式は、そのグループの概念（エンティティがそのグループの概念。例 所得税.法律婚）を依存する概念に書く。

    evaluate は、宣言したグループの組み立ての由来（婚姻の記録の印・扶養の所属の選択など）の状態をその値に付ける
    （人をまたぐ依存を通らずに役割だけを使う式でも、グループの組み立てに依存するため）。
    """
    p: list[ConceptProblem] = []
    for u in uses:
        c = d.by_variable(u.variable)
        if c is None:
            continue
        declared = {d.concept(t).entity for t in c.declared_targets() if d.get(t) is not None}
        if u.group not in declared:
            p.append(
                ConceptProblem(
                    "undeclared_group_use",
                    u.variable,
                    f"式がグループ {u.group} の組み方を使うが、{c.id} の依存する概念にエンティティが {u.group} の概念がない",
                )
            )
    return p


def _group(edges: Iterable[VariableEdge]) -> dict[str, list[str]]:
    g: dict[str, list[str]] = {}
    for e in edges:
        g.setdefault(e.source, []).append(e.target)
    return g


def check_parameters(d: ConceptDictionary, leaves: Iterable[str]) -> list[ConceptProblem]:
    """パラメータの葉が全部どれかの概念に宣言され、実装済みの概念の宣言が実在するか。"""
    p: list[ConceptProblem] = []
    leaves = sorted(set(leaves))
    for leaf in leaves:
        if not any(_covers(x, leaf) for c in d.concepts for x in c.parameters):
            p.append(ConceptProblem("unclaimed_parameter", leaf, "どの概念のパラメータにも含まれない"))
    for c in d.concepts:
        if not c.implemented:
            continue
        for x in c.parameters:
            if not any(_covers(x, leaf) for leaf in leaves):
                p.append(ConceptProblem("unknown_parameter", c.id, f"パラメータ {x} がない"))
        for b in c.boundaries:
            if not b.criterion_is_concept and b.criterion not in leaves:
                p.append(ConceptProblem("boundary", c.id, f"境目の基準 {b.criterion} がパラメータの葉でない"))
        for ab in c.age_boundaries:
            for name in (ab.criterion, ab.from_param):
                if name is not None and name not in leaves:
                    p.append(ConceptProblem("boundary", c.id, f"年齢の境目のパラメータ {name} がパラメータの葉でない"))
    return p


def check_parameter_use(d: ConceptDictionary, uses: Iterable[ParameterUse]) -> list[ConceptProblem]:
    """式が使ったパラメータが、その変数の概念に宣言されているか（制度をまたぐパラメータの使用もここで出る）。"""
    p: list[ConceptProblem] = []
    for u in uses:
        c = d.by_variable(u.variable)
        if c is None:
            continue
        if not any(_covers(x, u.parameter) for x in c.parameters):
            p.append(ConceptProblem("undeclared_parameter", u.variable, f"{c.id} のパラメータに {u.parameter} がない"))
        if u.cross_year and not any(x.is_parameter and _covers(x.target, u.parameter) for x in c.cross_year):
            p.append(ConceptProblem("undeclared_cross_year", u.variable, f"{u.parameter} を別の年で引くのに年をまたぐ依存に宣言がない"))
    return p


__all__ = [
    "CENTRAL_LAYER",
    "CONCEPTS_DIR",
    "MODULE_CONCEPTS_FILE",
    "PERIODS",
    "RULES_DIR",
    "Unimplemented",
    "VALUE_TYPES",
    "default_module_dirs",
    "FACT_LAYER",
    "INCOME_LAYER",
    "QUESTIONS",
    "AGE_REFERENCE_DAYS",
    "AgeBoundaryInfo",
    "BoundaryInfo",
    "Concept",
    "ConceptDictionary",
    "ConceptDictionaryError",
    "ConceptProblem",
    "DeclaredDependency",
    "Definition",
    "Institution",
    "Layer",
    "OutputInfo",
    "GroupUse",
    "ParameterUse",
    "Timing",
    "VariableEdge",
    "VariableInfo",
    "check_dictionary",
    "check_edges",
    "check_group_uses",
    "check_parameter_use",
    "check_parameters",
    "check_variables",
    "load_dictionary",
    "parse_dictionary",
    "read_files",
    "read_yaml",
]

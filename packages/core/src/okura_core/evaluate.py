"""判定コアの入口：evaluate(中間表現, 問い, 注入データ) → 結果（D7 改・D19・D21・D22、SCOPE §8）。

規則は持たない。規則モジュール（rules/<名前>/、registry.py）の宣言を組み合わせて評価する。

順序：
  1. 中間表現の項目の数の上限（scope.size_problems）・中間表現の検査（okura_ir.validate）・問い・注入データの検査。
     誤りがあれば結果の値を出さずに失敗を返す。
  2. シナリオごと（差分なしの base ＋ 問いのシナリオ。判断・選択の追記を足して中間表現を検査し直す）に：
     a. 対象外の検出（scope.py）：対象の年分の外、未対応の問い、どのモジュールも使わない記録・判断・選択・注入データ。
     b. 年分ごとに、その年分に生存している人だけで（生まれる前・死亡した年より後の人は入れない。記録は項目で返す）：
        - 判断・選択の1か所の値を決める（situation.resolve_decisions）。未入力の1か所・候補のある未注入の1か所・根拠のない端数と
          法令の読みの候補は「分かれ目」。
        - 値ごとに、その値が依存する分かれ目を計算の過程から決め（_resolve_dependencies：作り手が読んだ1か所と、トレースで推移的に
          依存した入力）、その分かれ目の候補の直積の全部の組について situation を作り（situation.build_year）、OpenFisca で計算する
          （トレースつき。2026-11-12 の4回目：以前は人のつながりごとに直積を取り、上限を超えたら分かれ目を1つずつ動かす近似で関係する
          値を決めていた）。関係のない分かれ目は最初の候補にする（その組合せは計算しない）。依存する分かれ目だけで直積が上限
          （candidates.MAX_ASSIGNMENTS）を超えた値は計算せず、未確定と依存する分かれ目を返す。
        - 所得税の年分の単位と同じ年の判定日の単位は、窓口を合わせた1つの situation で評価し、単位ごとの値の ID で返す（_shared_units）。
        - 段階評価（D23 K1）：宣言した段があれば、候補の組ごとに第1段の計算 → 段の間の純粋関数（前の段の値・関係から入力とグループを決める）
          → 次の段の計算 …を行い、最後に全部の値を計算する（_staged・situation.apply_stage）。段の読んだ値の状態・根拠・対象外は
          入力の由来（InputValue.uses）を通して最後の値へ伝わる。段の値は最後の計算の値と同じこと（違えば依存の宣言の誤り）を確かめる。
        - 候補の組ごとに値・状態・根拠・対象外を集め（_assemble）、値ごとに候補をまとめる（_merge_value：結論が同じなら断定、違えば未確定。
          根拠のない端数と単調な判断の両端評価で金額だけが違えば幅。D21 R6・D22 S3）。
     c. 状態の伝搬：入力の由来（記録・判断・選択の印：予測・見積り・計画）を、OpenFisca のトレースの依存に沿って、依存する値へ
        伝える。人をまたぐ依存（人でないエンティティの変数か、概念辞書の「人をまたぐ依存」の辺を通った）は、同じグループで
        つながった人の全部に依存させる（安全側）。グループの組み立ての由来の状態は、グループを使う値に付ける。対象外も同じ道で伝える。
        2026-11-13（B1 の直し）：つながった人の全部に依存させるのは、人をまたぐ辺を通った先で引いた変数だけ（_Closure.crossed。
        それ以外の変数は値の人の分だけ）。グループは、値の概念が宣言したグループだけ（attached_groups）。
     d. 対象外の規則（安全側。黙って近似しない）：
        - モジュールの対象外の検出（入力ごと・人ごと）と計算の後の検出（RuleModule.checks）。
        - 仮置きの変数（未実装の概念）に依存する値は対象外。ただし、その概念の「未実装のとき」の記録がその人・年分になければ0とみなす。
        - 集約点の集め忘れ：概念の「集める先」に集約点を書いた概念のうち、集約点がまだ引いていないものが、その人で0と言えなければ対象外
          （値が0でも、対象外の入力などから来る0は0と言えない）。
        - 式がほかの年分の値を引く値は対象外（situation は年分ごとで、ほかの年分の値は既定値になる）。
        - どのモジュールも使わない所得に関係しうる記録などがある人の、全部の所得に依存する値（scope.INCOME_RELATED_KINDS）。
     e. 境目の説明（概念辞書の「境目」）。
     f. 申告用の値：予測・未確定・対象外を含む申告者・年分からは出さない（result.build_filing）。
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import importlib.metadata
import json
import operator
import platform
import re
import threading
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any

import numpy
from openfisca_core import periods
from openfisca_core.indexed_enums import Enum
from openfisca_core.simulation_builder import SimulationBuilder

import okura_ir

from . import __version__
from .basis import BasisEntry, BasisType
from .candidates import MAX_ASSIGNMENTS, Assignment, Candidate, Merged, Slot, TooManyCandidates, assignments, merge
from .concepts import Concept, ConceptDictionary
from .country import OkuraTaxBenefitSystem, build_system, data_file_hashes, parameter_file_hashes
from .country.entities import ENTITIES
from .explain import TraceEntry, parameter_basis, period_key, sorted_unique, trace_graph
from .injection import InjectedData, parse_injected
from .query import FilingDate, Query, Scenario, parse_query
from .registry import (
    RECORD_SECTIONS,
    BasisContext,
    CheckContext,
    Decided,
    Exclusion,
    GroupInstance,
    InputValue,
    OutputSpec,
    Registry,
    MAX_FIXPOINT,
    StageSpec,
    StageValue,
    YearContext,
    YearWindow,
    alive_in_year,
    default_registry,
    memo,
    overlaps_year,
)
from .result import (
    RESULT_SCHEMA_VERSION,
    AgeBoundary,
    Boundary,
    Category,
    Comparison,
    Count,
    DateValue,
    EvaluationFailure,
    EvaluationResult,
    Flag,
    OutOfScopeCategory,
    OutOfScopeItem,
    OutOfScopeReason,
    Problem,
    ResultValue,
    ScenarioResult,
    Split,
    State,
    TimeKey,
    Undetermined,
    YenAmount,
    age_at_end_of,
    attained_on,
    build_filing,
    scenario_differences,
)
from .forms_output import form_specs, forms_for
from .scope import InputScope, input_scope, not_alive_items, residency_exclusions, size_problems, strings_in
from .situation import StageState, YearBuild, _reuse, apply_stage, build_year, resolve_decisions, rounding_slots
from .money import YenRange
from . import parallel as _parallel
from .timepoints import SUPPORTED_INCOME_TAX_YEARS, Unit, plan_units  # noqa: F401（年分の一覧は従来どおりここからも引ける）

#: 登録した規則モジュールと概念辞書（rules/__init__.py）。import の時点で辞書と登録の食い違いを検査する（あれば失敗する）。
REGISTRY: Registry = default_registry()
CONCEPTS: ConceptDictionary = REGISTRY.dictionary
#: 評価して結果に出す変数（概念辞書の「出力」から。依存の順）。
OUTPUTS: tuple[OutputSpec, ...] = REGISTRY.outputs
#: 境目の説明：判定の変数、比べる量の変数、基準のパラメータ、境目の ID。
BOUNDARIES: tuple[tuple[str, str, str, str, str | None], ...] = REGISTRY.boundaries


def _prefix(problems: list[Any], prefix: str) -> list[Problem]:
    out = []
    for p in problems:
        path = p.path
        out.append(Problem(prefix + path[1:] if path.startswith("$") else f"{prefix}.{path}", p.code, p.message))
    return out


def canonical_sha256(obj: Any) -> str:
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def versions(input_sha256: str, reg: Registry) -> dict[str, Any]:
    """結果の版。パラメータと表のデータの SHA-256 は登録ごとにプロセスで1回だけ求める（ファイルは評価の間に変えない約束）。"""
    cache = memo(reg, "versions")
    if "fixed" not in cache:
        cache["fixed"] = {
            "okura_core": __version__,
            "openfisca_core": importlib.metadata.version("openfisca-core"),
            "numpy": numpy.__version__,
            "python": platform.python_version(),
            "ir_schema": okura_ir.SCHEMA_VERSION,
            "result_schema": RESULT_SCHEMA_VERSION,
            "parameters_sha256": parameter_file_hashes(reg),
            "data_sha256": data_file_hashes(reg),
        }
    fixed = cache["fixed"]
    return {
        **{k: (dict(v) if isinstance(v, dict) else v) for k, v in fixed.items()},
        "input_sha256": input_sha256,
    }


_SCENARIO_PATH = re.compile(r"^\$\.(judgments|choices)\[(\d+)\](.*)$", re.S)


def apply_scenario(ir: Mapping[str, Any], scenario: Scenario, index: int) -> tuple[dict[str, Any], list[Problem]]:
    """シナリオの判断・選択の差分を中間表現に追記して検査し直す。"""
    if not scenario.judgments and not scenario.choices:
        return dict(ir), []
    merged = copy.deepcopy(dict(ir))
    base_len = {"judgments": len(ir["judgments"]), "choices": len(ir["choices"])}
    merged["judgments"] = merged["judgments"] + [copy.deepcopy(dict(j)) for j in scenario.judgments]
    merged["choices"] = merged["choices"] + [copy.deepcopy(dict(c)) for c in scenario.choices]
    problems: list[Problem] = _prefix(size_problems(merged), f"$.query.scenarios[{index}]")
    for p in okura_ir.validate(merged):
        m = _SCENARIO_PATH.match(p.path)
        if m and int(m.group(2)) >= base_len[m.group(1)]:
            k = int(m.group(2)) - base_len[m.group(1)]
            problems.append(Problem(f"$.query.scenarios[{index}].{m.group(1)}[{k}]{m.group(3)}", p.code, p.message))
        else:
            problems.append(Problem("$.ir" + p.path[1:], p.code, p.message))
    return merged, problems


def evaluate(
    ir: Any,
    query: Any,
    injected: Any = None,
    *,
    system: OkuraTaxBenefitSystem | None = None,
    registry: Registry | None = None,
) -> EvaluationResult | EvaluationFailure:
    """中間表現・問い・注入データから結果を出す純粋関数（同じ入力と同じ版なら同じ結果）。

    system は TaxBenefitSystem を使い回すとき（テストなど）に渡す。registry は登録の一覧を替えるとき（テストの道具のモジュール）
    に渡す（system を渡すなら system.registry と同じものであること）。どちらも None なら rules/__init__.py の登録を使う。
    """
    problems: list[Problem] = size_problems(ir)
    if problems:  # 大きすぎる入力は検査の前に止める（検査の時間は項目の数に比例する）
        return EvaluationFailure(tuple(problems))
    problems += _prefix(okura_ir.validate(ir), "$.ir")
    q, qp = parse_query(query, path="$.query")
    problems += qp
    inj, ip = parse_injected(injected, path="$.injected")
    problems += ip
    if q is not None and q.forms is not None and q.forms.persons is not None and isinstance(ir, Mapping):
        known = {p.get("id") for p in ir.get("persons", ()) if isinstance(p, Mapping)}
        for i, pid in enumerate(q.forms.persons):
            if pid not in known:
                problems.append(Problem(f"$.query.forms.persons[{i}]", "unknown_person", f"中間表現にない人: {pid}"))
    if problems or q is None or inj is None:
        return EvaluationFailure(tuple(problems))

    reg = registry if registry is not None else (system.registry if system is not None else REGISTRY)
    sys_ = system if system is not None else build_system(reg)
    if sys_.registry is not reg:
        raise ValueError("system と registry が違う登録の一覧から作られている")
    scenario_results: list[ScenarioResult] = []
    engines: dict[Any, _Engine] = {}  # 評価の単位ごとの Simulation の使い回し（シナリオをまたいで共有する：入力の違いだけを入れ直す）
    # 候補の組のプロセスの並列（2026-11-12 の5回目。parallel.py）：問いの workers（既定は CPU の数。1 なら直列）。ワーカーは既定の登録の
    # 一覧で体系を組み立てるので、registry を替えた評価（テストの道具のモジュール）は直列。結果は並列でも直列でも同じ
    workers = q.workers if q.workers is not None else _parallel.default_workers()
    use_pool = workers > 1 and reg is REGISTRY
    for i, sc in enumerate(q.all_scenarios()):
        ir_s, sp = apply_scenario(ir, sc, i - 1)
        if sp:
            problems += sp
            continue
        par = (lambda j, i=i: _parallel.Dispatcher(workers, (ir, query, injected, i, j))) if use_pool else None
        scenario_results.append(_evaluate_scenario(ir_s, q, inj, sys_, reg, sc, engines, par))
    if problems:
        return EvaluationFailure(tuple(problems))
    # 複数シナリオの一括評価（D19）：同じ法令の版（同じ system）で評価し、差分なしの base との値の差を機械的に出す（比べて選ぶのはアプリ）
    base = scenario_results[0]
    scenario_results = [base] + [replace(r, differences=scenario_differences(base.values, r.values)) for r in scenario_results[1:]]
    # 入力の SHA-256 は問いの実行の指定（workers：結果を変えない）を除いて求める（並列の数で結果が変わらないように）
    sha = canonical_sha256({"ir": ir, "query": without_execution_options(query), "injected": injected})
    return EvaluationResult(
        versions=versions(sha, reg),
        query=q.to_dict(),
        injected=tuple(e.to_summary() for e in inj.entries),
        scenarios=tuple(scenario_results),
    )


# ---------------------------------------------------------------------------
# 問いの時点と評価の単位（timepoints.py）
# ---------------------------------------------------------------------------


def _plan(q: Query, reg: Registry) -> tuple[tuple[Unit, ...], tuple[OutOfScopeItem, ...]]:
    """問いを評価の単位に分ける（所得税の年分・年度・判定日。年度 F は所得の年分 F−1 の situation）。"""
    return plan_units(
        q.income_tax_years,
        {
            "resident_tax_fiscal_years": q.resident_tax_fiscal_years,
            "kokuho_fiscal_years": q.kokuho_fiscal_years,
            "kokunen_fiscal_years": q.kokunen_fiscal_years,
        },
        q.dependent_judgment_dates,
        reg.available_questions(),
    )


def _evaluate_scenario(
    ir: Mapping[str, Any],
    q: Query,
    inj: InjectedData,
    system: OkuraTaxBenefitSystem,
    reg: Registry,
    sc: Scenario,
    engines: dict[Any, _Engine] | None = None,
    par: Any = None,
) -> ScenarioResult:
    """シナリオ1つの評価。par は評価の単位の番号 → parallel.Dispatcher（並列のとき）。"""
    scope = input_scope(ir, inj.entries, reg)
    units, q_items = _plan(q, reg)
    items = list(q_items) + list(scope.items)
    values: list[ResultValue] = []
    boundaries: list[Boundary] = []
    age_boundaries: list[AgeBoundary] = []
    asked: set[str] = set()
    results: dict[tuple[int, str], Any] = {}
    jobs = _unit_jobs(units, q, reg)

    def run_job(j: int) -> Any:
        unit, evaluated_unit, forms_specs, views = jobs[j]
        engine = engines.setdefault(unit.key, _Engine(system)) if engines is not None else None
        dispatch = par(j) if par is not None else None
        # views：同じ年の判定日の単位を1回の評価で答える（同じ計算の結果を共有する。2026-11-12 の4回目）
        return _evaluate_unit(ir, evaluated_unit, system, reg, scope, q.filing_date, inj, forms_specs, engine, views=views, dispatch=dispatch)

    if par is not None and len(jobs) > 1:
        # 並列のとき、評価の単位をスレッドで並べる（親はワーカーの結果を待つ間にほかの単位を進める。結果は単位の並びの順に入れる）
        with ThreadPoolExecutor(max_workers=len(jobs)) as tp:
            outs = list(tp.map(run_job, range(len(jobs))))
    else:
        outs = [run_job(j) for j in range(len(jobs))]
    for (unit, _evaluated, _specs, views), out in zip(jobs, outs):
        if views is None:
            results[unit.key] = out
        else:
            results[views[0].key], results[views[1].key] = out
    for unit in units:
        v, b, extra, unit_asked = results[unit.key]
        values += v
        boundaries += [x for x in b if isinstance(x, Boundary)]
        age_boundaries += [x for x in b if isinstance(x, AgeBoundary)]
        items += extra
        asked |= unit_asked
    filing_date = q.filing_date.on if q.filing_date is not None else None
    # 申告用の値は、問いが求めた時点の値からだけ作る（依存先として出した前年分の所得税の値などからは作らない）
    entries, withheld = build_filing([v for v in values if v.id in asked], filing_date=filing_date)
    forms: tuple[Any, ...] = ()
    if q.forms is not None:
        persons = q.forms.persons if q.forms.persons is not None else tuple(p["id"] for p in ir["persons"])
        years = [y for y in q.income_tax_years if y in SUPPORTED_INCOME_TAX_YEARS]
        forms = forms_for(values, persons, years, filing_date)
    return ScenarioResult(
        id=sc.id,
        label=sc.label,
        values=tuple(values),
        boundaries=tuple(boundaries),
        out_of_scope=tuple(_unique_items(items)),
        filing=entries,
        withheld=withheld,
        forms=forms,
        age_boundaries=tuple(age_boundaries),
    )


def _unit_jobs(
    units: Iterable[Unit], q: Query, reg: Registry
) -> list[tuple[Unit, Unit, tuple[OutputSpec, ...], tuple[Unit, Unit] | None]]:
    """評価の単位の評価の並び：(単位, 評価する単位, 欄が読む途中の概念, 一緒に答える単位の並び〔なければ None〕)。

    所得税の年分の単位は、同じ年の判定日の単位と一緒に評価する（_shared_units。評価する単位は窓口を合わせたもの）。
    親とワーカー（_worker_handle）が同じ並びを作る（並びの番号で単位を指す）。
    """
    units = list(units)
    shared = _shared_units(units)
    jobs: list[tuple[Unit, Unit, tuple[OutputSpec, ...], tuple[Unit, Unit] | None]] = []
    done: set[tuple[int, str]] = set()
    for unit in units:
        if unit.key in done:
            continue  # 所得税の年分の単位と一緒に評価した判定日の単位
        forms_specs: tuple[OutputSpec, ...] = ()
        if q.forms is not None and unit.on is None and unit.income_year in q.income_tax_years:
            forms_specs = form_specs(reg, unit.income_year, reg.outputs)  # 欄が読む途中の概念も結果に出す
        partner = shared.get(unit.key)
        if partner is None:
            jobs.append((unit, unit, forms_specs, None))
            done.add(unit.key)
        else:
            both = Unit(unit.income_year, None, unit.windows + partner.windows)
            jobs.append((unit, both, forms_specs, (unit, partner)))
            done |= {unit.key, partner.key}
    return jobs


def _shared_units(units: Iterable[Unit]) -> dict[tuple[int, str], Unit]:
    """所得税の年分の単位（on なし）→ 同じ situation で一緒に評価する、同じ年の判定日の単位（2026-11-12 の4回目）。

    判定日の単位は所得税の全部の値（段階評価の段が読む）を計算するので、同じ年の年分の単位と同じ計算を繰り返していた。
    窓口の（制度, 問い）が重ならないとき（年分の単位：所得税・住民税・国保・国年の年度、判定日の単位：健保・国年の判定日）、
    窓口を合わせた1つの situation で評価し、単位ごとの見え方（値の ID）で返す。同じ年の判定日が2つ以上あれば最初の1つだけ
    （判定日ごとの値の変数は1つの situation に1つの判定日しか入らない）。
    """
    units = list(units)
    out: dict[tuple[int, str], Unit] = {}
    taken: set[tuple[int, str]] = set()
    for u in units:
        if u.on is not None:
            continue
        own = {(w.institution, w.question) for w in u.windows}
        for d in units:
            if d.on is None or d.income_year != u.income_year or d.key in taken:
                continue
            if own.isdisjoint((w.institution, w.question) for w in d.windows):
                out[u.key] = d
                taken.add(d.key)
            break  # その年の最初の判定日だけ
    return out


def _unique_items(items: Iterable[OutOfScopeItem]) -> list[OutOfScopeItem]:
    """同じ項目を重ねない（同じ年分の単位が2つ以上あると、生存していない人の記録の項目が重なる）。順は最初に出た順。"""
    seen: set[str] = set()
    out: list[OutOfScopeItem] = []
    for it in items:
        k = json.dumps(it.to_dict(), ensure_ascii=False, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def unit_outputs(reg: Registry, unit: Unit) -> tuple[tuple[OutputSpec, ...], frozenset[str]]:
    """評価の単位で計算する出力（依存の順）と、そのうち問いが求めたもの（変数の名前）。

    - 問いが求めたもの：概念の（制度, 問い）が単位の窓口のどれかと合う出力。
    - 計算するもの：求めたものと、宣言した依存をたどって届く出力。求めたものが所得税の概念に届くなら所得税の出力の全部
      （段階評価の段が読む値〔合計所得金額など〕は宣言した依存に現れないので、所得税の側を全部そろえる）。
    結果には、求めたものと、その depends_on をたどって届く値だけを出す（_evaluate_unit）。
    """
    d = reg.dictionary
    asked = [
        o for o in reg.outputs if unit.window_for(d.concept(o.concept).institution, d.concept(o.concept).timing.question) is not None
    ]
    reach: set[str] = set()
    for o in asked:
        reach |= {c.id for c in d.closure(o.concept)}
    if any(d.concept(c).institution == "所得税" for c in reach):
        reach |= {o.concept for o in reg.outputs if d.concept(o.concept).institution == "所得税"}
    asked_vars = frozenset(o.variable for o in asked)
    specs = tuple(o for o in reg.outputs if o.variable in asked_vars or o.concept in reach)
    return specs, asked_vars


def _id_function(unit: Unit, d: ConceptDictionary) -> Any:
    """（概念 ID, 人）→ 値の ID。時点の部分は単位と概念の問いから（Unit.tag）。"""
    tags: dict[str, str] = {}

    def value_id(concept_id: str, person: str) -> str:
        tag = tags.get(concept_id)
        if tag is None:
            c = d.concept(concept_id)
            tag = tags[concept_id] = unit.tag(unit.time_of(c.institution, c.timing.question))
        return f"v:{tag}:{person}:{concept_id}"

    return value_id


def _time_function(unit: Unit, d: ConceptDictionary) -> Any:
    def time_of(concept_id: str) -> TimeKey:
        c = d.concept(concept_id)
        return unit.time_of(c.institution, c.timing.question)

    return time_of


def _prune(values: list[ResultValue], asked_vars: frozenset[str]) -> tuple[list[ResultValue], frozenset[str]]:
    """問いが求めた値と、その depends_on をたどって届く値だけを残す（並びは元のまま）。求めた値の ID も返す。"""
    by_id = {v.id: v for v in values}
    asked_ids = {v.id for v in values if v.variable in asked_vars}
    keep: set[str] = set()
    stack = list(asked_ids)
    while stack:
        vid = stack.pop()
        if vid in keep or vid not in by_id:
            continue
        keep.add(vid)
        stack.extend(by_id[vid].depends_on)
    return [v for v in values if v.id in keep], frozenset(asked_ids)


# ---------------------------------------------------------------------------
# トレースの依存
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Closure:
    """出力の変数の式が引いたもの（出力の変数で止める）。"""

    out_deps: frozenset[str]  # 直接引いた出力の変数
    inputs: frozenset[str]  # 出力でない入力変数（式のない変数。仮置きの変数を含む）
    params: frozenset[tuple[str, str]]
    variables: frozenset[str]  # 通った変数の全部（出力の変数を除く）
    cross: bool  # 人をまたぐ依存（人でないエンティティの変数を通った、又は概念辞書の「人をまたぐ依存」の辺を通った）
    other_years: frozenset[str]  # ほかの年分の値を引いた変数（situation は年分ごとなので、その値は入っていない）
    #: 人をまたぐ辺（概念辞書の「人をまたぐ依存」の辺・人でないエンティティの変数）を通った先で引いた変数（variables・inputs・out_deps の
    #: 部分）。ほかの人の値として読みうる。ここにない変数は、値の人と同じ人についてだけ読む（式は人ごとの計算で、ほかの人の値を読むのは
    #: 人をまたぐ読み方だけ：構造の検査が式の AST で見つけ、宣言を求める）。2026-11-13（B1 の直し）：以前は、人をまたぐ値は通った変数の
    #: 全部を、つながった人の全部について依存に数えていた（本人についてだけ読む住所地の市町村の級地などが、家族の全員の分で数えられた）
    crossed: frozenset[str] = frozenset()

    def readers(self, name: str, person: str, scope: Any) -> Any:
        """変数 name の値を、だれについて読みうるか：人をまたいだ先で引いた変数ならつながった人（scope）、そうでなければ値の人だけ。"""
        return scope if name in self.crossed else (person,)


def cross_person_edges(d: ConceptDictionary) -> frozenset[tuple[str, str]]:
    """概念辞書の「人をまたぐ依存」の辺（引く変数, 引かれる変数）。

    人の変数が人の変数を引くとき（`人.法律婚.members("…", period)`・`人.扶養所属.sum(人("…", period))` など）、OpenFisca の
    トレースには同じ人の変数を引いたのと同じ形でしか残らない。人をまたぐかどうかは、構造の検査（tests/test_architecture.py：
    式の AST で人をまたぐ読み方を見つけ、宣言を求める）が保証する辞書の宣言から決める。辞書ごとに1回だけ求める。
    """
    cache = memo(d, "cross_person_edges")
    if "edges" not in cache:
        cache["edges"] = _cross_person_edges(d)
    return cache["edges"]


def _cross_person_edges(d: ConceptDictionary) -> frozenset[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for c in d.concepts:
        for dep in c.cross_person:
            t = d.get(dep.target)
            if t is None:
                continue
            out |= {(sv, tv) for sv in c.variables for tv in t.variables}
    return frozenset(out)


def _closure(
    graph: Mapping[tuple[str, str], Any],
    var: str,
    year: int,
    system: OkuraTaxBenefitSystem,
    outputs: set[str],
    xp: frozenset[tuple[str, str]] = frozenset(),
) -> _Closure:
    key = (var, f"year:{year}-01-01:1")
    out_deps: set[str] = set()
    inputs: set[str] = set()
    params: set[tuple[str, str]] = set()
    seen_vars: set[str] = set()
    other_years: set[str] = set()
    crossed_names: set[str] = set()
    cross = False
    entry = graph.get(key)
    if entry is None:
        return _Closure(frozenset(), frozenset(), frozenset(), frozenset(), False, frozenset())
    params |= entry.parameters
    # 値の変数そのものが人でないエンティティの変数なら、引くものは全部グループの人の値（人をまたいだ先）
    root_var = system.variables.get(var)
    root_crossed = root_var is not None and not root_var.entity.is_person
    stack: list[tuple[str, tuple[str, str], bool]] = [(var, c, root_crossed) for c in entry.children]
    seen: dict[tuple[str, str], bool] = {}  # たどった項目 → 人をまたいだ先としてたどったか
    while stack:
        parent, child, crossed = stack.pop()
        v = system.variables[child[0]]
        if (parent, child[0]) in xp:
            cross = True
            crossed = True
        if not v.entity.is_person:
            crossed = True
        if child[1] != key[1] and child[1].startswith("year:"):
            other_years.add(child[0])
        done = seen.get(child)
        if done is not None and (done or not crossed):
            continue  # 同じか、より広い読み方（人をまたいだ先）でたどってある
        seen[child] = crossed
        if crossed:
            crossed_names.add(child[0])
        if child[0] in outputs and v.entity.is_person and child[1] == key[1]:
            out_deps.add(child[0])
            continue
        seen_vars.add(child[0])
        if not v.entity.is_person:
            cross = True
        if not v.formulas:
            inputs.add(child[0])
        sub = graph.get(child)
        if sub is not None:
            params |= sub.parameters
            stack.extend((child[0], c, crossed) for c in sub.children)
    return _Closure(
        frozenset(out_deps), frozenset(inputs), frozenset(params), frozenset(seen_vars), cross, frozenset(other_years),
        frozenset(crossed_names),
    )


def _components(groups: Mapping[str, Any], order: list[str]) -> dict[str, int]:
    """人 → グループ（全部の種類）でつながった人の集まりの番号。人をまたぐ依存はグループの中でしか起こらない（OpenFisca）。"""
    parent = {p: p for p in order}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for insts in groups.values():
        for inst in insts:
            members = [p for ps in inst.roles.values() for p in ps]
            for a, b in zip(members, members[1:]):
                parent[find(a)] = find(b)
    roots: dict[str, int] = {}
    return {p: roots.setdefault(find(p), len(roots)) for p in order}


# ---------------------------------------------------------------------------
# 年分の評価
# ---------------------------------------------------------------------------


def _value_id(year: int, person: str, concept: str) -> str:
    """所得税の年分の値の ID（年度・判定日の値は Unit.tag の時点の部分：_id_function）。"""
    return f"v:{year}:{person}:{concept}"


def _merge_reasons(reasons: list[OutOfScopeReason]) -> OutOfScopeReason:
    """複数の対象外の理由を1つにする：区分は最初のもの、理由は重ねずにつなぎ、記録の ID は足し合わせる。"""
    reasons = list(dict.fromkeys(reasons))  # 同じ理由は1回（結果は変わらない）
    texts = list(dict.fromkeys(r.reason for r in reasons))
    ids = sorted({i for r in reasons for i in r.record_ids})
    return OutOfScopeReason(reasons[0].category, "／".join(texts), tuple(ids))


def _zero_index(reg: Registry, ir: Mapping[str, Any], year: int) -> dict[tuple[str, str], list[str]]:
    """（記録の種類, 人）→ その年分と重なる記録の ID。「未実装のとき」が見る種類だけ（人数の2乗にならないよう、先に作る）。"""
    kinds: set[str] = {k for c in reg.dictionary.concepts if c.unimplemented is not None for k in c.unimplemented.zero_record_kinds}
    out: dict[tuple[str, str], list[str]] = {}
    for s in ("relations", "residences", "insurance_memberships", "facts", "assets", "filed_documents"):
        for r in ir[s]:
            if r["kind"] in kinds and overlaps_year(r.get("when"), year):
                for person in set(r.get("roles", {}).values()):
                    out.setdefault((r["kind"], person), []).append(r["id"])
    return out


def _zero_blockers(concept: Concept, person: str, index: Mapping[tuple[str, str], list[str]]) -> tuple[bool, tuple[str, ...]]:
    """未実装の概念の値を、その人・年分で0とみなしてよいか（よくなければ、その原因の記録の ID）。"""
    if concept.unimplemented is None:
        return False, ()
    ids = sorted(i for k in set(concept.unimplemented.zero_record_kinds) for i in index.get((k, person), ()))
    return (not ids), tuple(ids)


def _placeholder_reason(concept: Concept, ids: tuple[str, ...]) -> OutOfScopeReason:
    text = f"依存する概念 {concept.id}（担当 {concept.module}）が未実装"
    if ids:
        text += "で、この人にその材料の記録がある"
    return OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, text, ids)


def _to_python(raw: Any, value_type: str) -> Any:
    if value_type in ("円", "整数"):
        return int(raw)
    if value_type == "真偽":
        return bool(raw)
    if value_type == "区分":
        return str(raw)
    if value_type == "日付":
        d = numpy.datetime64(raw, "D").astype(object)
        if not isinstance(d, _dt.date):
            raise TypeError("日付の値を date にできない")
        return d
    raise ValueError(f"知らない値の型: {value_type}")


def _to_value(v: Any, value_type: str) -> Any:
    if isinstance(v, YenRange):
        return v
    if value_type == "円":
        return YenAmount(v)
    if value_type == "真偽":
        return Flag(v)
    if value_type == "整数":
        return Count(v)
    if value_type == "区分":
        return Category(v)
    return DateValue(v)


class _InputIndex:
    """入力（変数, 人）の集まりを、整数のビットの集まりで持つための番号（評価の単位ごとに1つ。計算の速さのため。2026-11-12）。

    _Raw.inputs は推移的に依存した入力の集まりで、値ごとに依存の値の集まりの和を取る（家族1組で数千の要素の和を数万回）。
    ビットの論理和にすると和が速い。段に渡す StageValue.inputs は従来どおり frozenset（to_set で戻す。同じ集まりは1回だけ作る）。
    """

    def __init__(self) -> None:
        self.bit: dict[tuple[str, str], int] = {}
        self.keys: list[tuple[str, str]] = []
        self._sets: dict[int, frozenset[tuple[str, str]]] = {}
        self._bits: dict[int, tuple[frozenset[tuple[str, str]], int]] = {}  # id(集まり) →（集まり, ビット）。集まりを持っておく

    def of(self, key: tuple[str, str]) -> int:
        b = self.bit.get(key)
        if b is None:
            b = self.bit[key] = 1 << len(self.keys)
            self.keys.append(key)
        return b

    def from_set(self, keys: frozenset[tuple[str, str]]) -> int:
        hit = self._bits.get(id(keys))
        if hit is not None and hit[0] is keys:
            return hit[1]
        b = 0
        of = self.of
        for k in keys:
            b |= of(k)
        self._bits[id(keys)] = (keys, b)
        return b

    def to_set(self, bits: int) -> frozenset[tuple[str, str]]:
        hit = self._sets.get(bits)
        if hit is None:
            if bits:
                raw = numpy.frombuffer(bits.to_bytes((bits.bit_length() + 7) // 8, "little"), dtype=numpy.uint8)
                keys = self.keys
                hit = frozenset([keys[i] for i in numpy.flatnonzero(numpy.unpackbits(raw, bitorder="little")).tolist()])
            else:
                hit = frozenset()
            self._sets[bits] = hit
            self._bits[id(hit)] = (hit, bits)
        return hit


@dataclass
class _Raw:
    """候補の組1つの評価での、出力の変数 × 人 の値。"""

    value: Any
    states: set[State]
    facts: set[str]
    deps: set[str]
    reasons: list[OutOfScopeReason]
    basis: list[BasisEntry]
    has_records: bool
    inputs: Any  # 推移的に依存した入力（変数, 人）。evaluate では _InputIndex のビット（int）、単体の道具では frozenset でもよい（_merge_value）
    missing: dict[str, Split] = field(default_factory=dict)  # 依存した、注入されていない（候補を持たない）注入点の分かれ目
    #: 値そのものの入力ではないが、対象外の理由を変えうる入力（集め忘れの検出が見る値の入力。ビット）。依存する分かれ目を決めるのに使い、
    #: 「関係する分かれ目」（evaluated）の判定には使わない（2026-11-12 の4回目）
    extra: int = 0


@dataclass
class _Sim:
    """候補の組1つの OpenFisca の計算（出力の変数まで計算したもの）。同じ候補の組は1回だけ計算する。"""

    build: YearBuild
    sim: Any
    cache: dict[str, Any]
    read_rounding: frozenset[str]  # 式か build_inputs が実際に読んだ、根拠のない端数の分かれ目の ID
    state: StageState | None = None  # 段階評価の出力（段がなければ None）
    engine: _Engine | None = None  # 段の回をまたいで Simulation を使い回すとき（なければこの回だけの Simulation）
    raws: dict[tuple[str, str], _Raw] | None = None  # 最後の計算の全員の値（staged が集める）
    #: 候補の組1つの評価の全部の situation（段の回と最後）と段の関数で、作り手が読んだ1か所（作り手 → {(種類, key)}。値ごとの候補の評価）
    reads: dict[Any, set[tuple[str, str]]] | None = None
    #: 計算の後の検出ごと・人ごとの、検出が読んだ値の入力（ビット）と、検出が出した対象外（(検出の番号, 変数か None, 人)）
    check_bits: dict[tuple[int, str], int] = field(default_factory=dict)
    check_targets: frozenset[tuple[int, str | None, str]] = frozenset()

    def graph(self) -> dict[tuple[str, str], TraceEntry]:
        """この回の計算のトレースの依存（_Engine.round_graph：新しい Simulation で計算したときと同じもの）。"""
        if self.engine is not None:
            if self.engine.current is None or self.engine.current.sim is not self.sim:
                raise AssertionError("使い回した Simulation のトレースを、次の計算の後に読んだ")
            return self.engine.round_graph()
        return trace_graph(self.sim.tracer)


class _TraceNode:
    """_DependencyTracer の記録の1つ（OpenFisca の TraceNode のうち、依存の表に使う名前・期間・子・パラメータだけ）。"""

    __slots__ = ("name", "period", "children", "parameters", "parent")

    def __init__(self, name: str, period: Any, parent: _TraceNode | None) -> None:
        self.name = name
        self.period = period
        self.children: list[_TraceNode] = []
        self.parameters: list[_TraceNode] = []
        self.parent = parent


class _DependencyTracer:
    """OpenFisca の FullTracer の代わりに、計算の依存（変数・期間の木とパラメータの参照）だけを記録するトレーサー（計算の速さのため）。

    Simulation が使う窓口（stack・record_calculation_start/result/end・record_parameter_access）と、依存の表を作る trees・browse_trace
    だけを持つ。木の形（呼んだ順の子・パラメータ）は FullTracer と同じ。値と時間は記録しない（判定コアは使わない）。
    stack は SimpleTracer と同じ形（{"name", "period"}。循環の検出に使われる）。
    """

    def __init__(self) -> None:
        self.stack: list[dict[str, Any]] = []
        self.trees: list[_TraceNode] = []
        self._current: _TraceNode | None = None

    def record_calculation_start(self, variable: str, period: Any) -> None:
        self.stack.append({"name": variable, "period": period})
        node = _TraceNode(variable, period, self._current)
        if self._current is None:
            self.trees.append(node)
        else:
            self._current.children.append(node)
        self._current = node

    def record_calculation_result(self, value: Any) -> None:
        pass

    def record_parameter_access(self, parameter: str, period: Any, value: Any) -> None:
        if self._current is not None:
            self._current.parameters.append(_TraceNode(parameter, period, None))

    def record_calculation_end(self) -> None:
        self.stack.pop()
        if self._current is not None:
            self._current = self._current.parent

    def browse_trace(self) -> Iterable[_TraceNode]:
        stack = list(reversed(self.trees))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))


class _SimState:
    """グループの組み方1つ（と人の並び）の Simulation と、その計算の依存の表。"""

    def __init__(self, sim: Any, build: YearBuild) -> None:
        self.sim = sim
        self.build = build
        self.persistent: dict[tuple[str, str], TraceEntry] = {}
        #: persistent の辺の逆向き（子 → 親）。_absorb が足し、_update が消した項目の分を外す（毎回作り直さない）
        self.parents: dict[tuple[str, str], set[tuple[str, str]]] = {}
        #: トレースの閉包の使い回し（変数, 止める出力）→（求めたときの項目, 閉包）。項目が消えて作り直されたら使わない（_assemble）
        self.closures: dict[tuple[str, frozenset[str]], tuple[TraceEntry, _Closure]] = {}
        #: 閉包の通った変数 × 人の組（_assemble。閉包のオブジェクトを持っておく：id を使い回されないように）
        self.pairs: dict[tuple[int, tuple[str, ...], int], tuple[_Closure, _InputIndex, int]] = {}
        self.periods: dict[tuple[str, str], Any] = {}
        self.done = 0  # この回のトレーサーの木のうち、persistent に入れた数
        self.round_keys: set[tuple[str, str]] = set()
        self.graph: dict[tuple[str, str], TraceEntry] | None = None  # round_graph の結果（新しい計算がなければ使い回す）


#: _assemble の止める出力が全部の出力と同じになるときのキー（回をまたいでトレースの閉包を使い回す）
_ALL_OUTPUTS: frozenset[str] = frozenset({"\0全部の出力"})


def _input_parts(build: YearBuild) -> tuple[tuple[Mapping[tuple[str, str], InputValue], ...], Mapping[tuple[str, str], InputValue]]:
    """入力をモジュールごとの部分と段の出力に分けたもの（build_year が付ける。なければ全体を1つの部分にする）。"""
    parts = build.__dict__.get("_input_parts")
    return parts if parts is not None else ((build.inputs,), {})


class _Engine:
    """評価の単位1つの中で、OpenFisca の Simulation を使い回す（計算の速さのため）。

    段階評価の回ごと・候補の組ごとに新しい Simulation を作る代わりに、同じグループの組み方（と人の並び）の Simulation に
    入力の違いだけを入れ直し、違った入力に（トレースで）依存した計算済みの値だけを消して計算し直す。グループの組み方ごとに
    Simulation を1つ持つ（段がグループを書く前と後で別の Simulation になる）。結果は、毎回新しい Simulation で計算したときと
    同じになるように作る：
    - 値：式は入力とパラメータの純粋関数なので、依存した入力が変わらない計算済みの値は、新しく計算しても同じ。
      なくなった入力は Holder から消す（新しい Simulation で書かなかったのと同じ：式があれば式、なければ既定値）。
    - トレースの依存（round_graph）：回ごとに新しいトレーサーで記録し、その回に引いた（変数, 期間）から、計算をまたいで持つ
      依存の表（persistent）をたどった部分を返す。新しい Simulation では、その回に引いた値の依存の全部をその回に計算するので、同じ集まり。
    - 1回の計算の結果（_Sim）は、次に prepare を呼ぶまでの間だけ使える（計算した値の配列 cache は、その後も使える）。
    """

    def __init__(self, system: OkuraTaxBenefitSystem) -> None:
        self.system = system
        self.states: dict[tuple[tuple[str, ...], str], _SimState] = {}
        self.current: _SimState | None = None
        self.fresh = 0  # 新しく作った Simulation の数（測定用）
        self.rounds = 0

    def prepare(self, build: YearBuild, period: Any) -> Any:
        """この回の situation を入れた Simulation（新しいトレーサーつき）。"""
        if self.current is not None:
            self._absorb(self.current)
        key = (tuple(build.persons), build.group_signature())
        st = self.states.get(key)
        if st is None:
            st = self.states[key] = _SimState(new_simulation(self.system, build, period), build)
            self.fresh += 1
        else:
            self._update(st, build, period)
        st.build = build
        st.sim.trace = True  # この回のトレーサー（依存だけを記録するもの。parameters_at の追跡は trace が真のときだけ）
        st.sim.tracer = _DependencyTracer()
        st.done = 0
        st.round_keys = set()
        st.graph = None
        self.current = st
        self.rounds += 1
        return st.sim

    def _update(self, st: _SimState, build: YearBuild, period: Any) -> None:
        """前に使ったときとの入力の違いを入れ直し、違った入力に依存した計算済みの値を消す。"""
        old = st.build.inputs
        new = build.inputs
        if old is new:
            return  # 同じ入力（build_year が材料の同じときに返す同じオブジェクト）
        # 比べるのは、同じオブジェクトでない入力の部分だけ（build_year のモジュールごとの部分・段の出力。_input_parts）
        old_parts, old_stage = _input_parts(st.build)
        new_parts, new_stage = _input_parts(build)
        if len(old_parts) == len(new_parts):
            pairs = [(a, b) for a, b in zip(old_parts, new_parts) if a is not b] + [(old_stage, new_stage)]
        else:
            pairs = [(old, new)]
        changed: set[str] = set()
        gone: set[tuple[str, str]] = set()
        for o, n in pairs:
            if o is n:
                continue
            for k, iv in n.items():
                prev = o.get(k)
                if prev is None or type(prev.value) is not type(iv.value) or prev.value != iv.value:
                    changed.add(k[0])
            gone.update(k for k in o if k not in n)
        removed = {k[0] for k in gone if k not in new}
        changed |= removed
        if not changed:
            return
        sim = st.sim
        persons = build.persons
        if any((name, p) in new for name in removed for p in persons):
            raise AssertionError("入力が一部の人だけなくなった")
        for name in sorted(removed):
            sim.get_holder(name).delete_arrays()  # 書かない入力：新しい Simulation と同じく、式か既定値で計算する
        sub = YearBuild({}, persons, {(v, p): new[(v, p)] for v in changed for p in persons if (v, p) in new}, (), {})
        _set_inputs(self.system, sim, sub, period, clear_skipped=True)
        parents = st.parents
        start = [k for k in st.persistent if k[0] in changed]
        dead: set[tuple[str, str]] = set(start)
        stack = list(start)
        while stack:
            k = stack.pop()
            for p in parents.get(k, ()):
                if p not in dead:
                    dead.add(p)
                    stack.append(p)
        for key in dead:
            entry = st.persistent.pop(key, None)
            if entry is not None:
                for child in entry.children:
                    ps = parents.get(child)
                    if ps is not None:
                        ps.discard(key)
            if key[0] not in changed:
                sim.get_holder(key[0]).delete_arrays(st.periods[key])

    def _absorb(self, st: _SimState) -> list[tuple[str, str]]:
        """この回のトレーサーの、まだ入れていない木を persistent に入れる（計算した値の依存。キャッシュから返した値は子を持たない）。
        入れた木の項目のキーを返す。"""
        trees = st.sim.tracer.trees
        persistent = st.persistent
        parents = st.parents
        visited: list[tuple[str, str]] = []
        for tree in trees[st.done:]:
            stack = [tree]
            while stack:
                node = stack.pop()
                key = (node.name, period_key(node.period))
                st.periods.setdefault(key, node.period)
                st.round_keys.add(key)
                visited.append(key)
                entry = persistent.get(key)
                if entry is None:
                    entry = persistent[key] = TraceEntry()
                for child in node.children:
                    ck = (child.name, period_key(child.period))
                    entry.children.add(ck)
                    ps = parents.get(ck)
                    if ps is None:
                        ps = parents[ck] = set()
                    ps.add(key)
                    stack.append(child)
                for p in node.parameters:
                    entry.parameters.add((p.name, str(p.period)))
        st.done = len(trees)
        return visited

    def round_graph(self) -> dict[tuple[str, str], TraceEntry]:
        """この回に引いた（変数, 期間）と、その依存をたどった部分（新しい Simulation のトレースと同じ集まり）。"""
        st = self.current
        assert st is not None
        if st.graph is not None and st.done == len(st.sim.tracer.trees):
            return st.graph  # 前に求めた後に新しい計算がない
        visited = self._absorb(st)
        # 前に求めた集まりに、新しく引いたものとその依存を足す（同じ回の中では persistent の項目は消えず、子が増えるだけ。
        # 新しく引いた項目は visited に入るので、その項目の今の中身と子をたどり直す。前の結果の辞書は変えない）
        out: dict[tuple[str, str], TraceEntry] = dict(st.graph) if st.graph is not None else {}
        stack: list[tuple[str, str]] = []
        for k in (visited if st.graph is not None else st.round_keys):
            entry = st.persistent.get(k)
            if entry is None:
                entry = TraceEntry()
            out[k] = entry
            stack.extend(entry.children)
        while stack:
            k = stack.pop()
            if k in out:
                continue
            entry = st.persistent.get(k)
            if entry is None:
                entry = TraceEntry()
            out[k] = entry
            stack.extend(entry.children)
        st.graph = out
        return out


@dataclass
class _Run:
    assignment: Assignment
    build: YearBuild
    sim: _Sim | None = None
    raws: dict[tuple[str, str], _Raw] = field(default_factory=dict)
    index: _InputIndex | None = None  # raws の inputs のビットの番号（_assemble が入れる）
    check_bits: dict[tuple[int, str], int] = field(default_factory=dict)  # _assemble(check_deps=True) が入れる（_Sim.check_bits）
    check_targets: frozenset[tuple[int, str | None, str]] = frozenset()


class _RoundNode:
    """段階評価の1つの回の結果（候補の組をまたいで使い回す。計算の速さのため。2026-11-12）。

    回 r の段に渡す値（段の読む変数の StageValue：値・状態・事実・根拠・対象外・依存）と、段の値の確かめに使う配列と、
    式が引いた端数の候補は、その回の situation のうち「値を集めるのに使った変数（段の読む値・集めた値・計算の後の検出・
    集め忘れの検出・根拠が引いたもの）がトレースで依存した変数」の入力（値と由来）と、対象外の検出・グループの組み方・人の並びだけで決まる
    （式は入力とパラメータの純粋関数で、引いた入力が同じなら同じ分岐を通って同じ変数を引く。値の集め方はトレース・入力の由来・
    対象外の検出・グループの関数）。それらが前に計算した回と同じなら、OpenFisca の計算と値の集め方をせずに同じ値を使う。
    段の関数（apply_stage）は候補の組ごとに今の判断・選択で実行する（段の関数が読む判断が違っても、段に渡す値は使い回せる）。
    """

    __slots__ = ("inputs", "traced", "exclusions", "groups", "persons", "values", "checks", "read_rounding")

    def __init__(
        self,
        traced: frozenset[str],
        build: YearBuild,
        values: dict[str, dict[tuple[str, str], StageValue]],
        checks: dict[str, tuple[tuple[str, Any], ...]],
        read_rounding: frozenset[str],
    ) -> None:
        self.traced = traced
        self.inputs = {k: iv for k, iv in build.inputs.items() if k[0] in traced}
        self.exclusions = build.exclusions
        self.groups = build.groups
        self.persons = build.persons
        self.values = values
        self.checks = checks
        self.read_rounding = read_rounding

    def keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self.inputs))

    def matches(self, build: YearBuild) -> bool:
        if build.persons != self.persons or build.exclusions != self.exclusions or build.groups != self.groups:
            return False
        got = build.inputs
        for k, iv in self.inputs.items():
            now = got.get(k)
            if now is not iv and (now is None or type(now.value) is not type(iv.value) or now != iv):
                return False
        names = self.traced
        return sum(1 for k in got if k[0] in names) == len(self.inputs)  # 使った変数の入力が増えていない


_VALUE_OF = operator.attrgetter("value")


class _RoundMemo:
    """回ごとの _RoundNode の表。使った変数の集まりごとに、入力の値（型と値）の組で引く（全部の節と比べない）。"""

    def __init__(self) -> None:
        self.rounds: dict[int, dict[frozenset[str], tuple[tuple[tuple[str, str], ...], dict[tuple[Any, ...], list[_RoundNode]]]]] = {}
        #: 同じ YearBuild のオブジェクト（build_year が材料の同じときに返す）で前に見つけた節：(回, id) →（build, 節）
        self.by_build: dict[tuple[int, int], tuple[YearBuild, _RoundNode]] = {}

    @staticmethod
    def _value_key(build: YearBuild, keys: tuple[tuple[str, str], ...]) -> tuple[Any, ...] | None:
        # 入力の値の並びと型の並び（値と型の組の並びと同じ等しさ。C の map で作る：計算の速さのため）
        try:
            values = tuple(map(_VALUE_OF, map(build.inputs.__getitem__, keys)))
        except KeyError:
            return None  # その回の入力がない（使った変数の入力が減った）
        return (values, tuple(map(type, values)))

    def find(self, r: int, build: YearBuild) -> _RoundNode | None:
        known = self.by_build.get((r, id(build)))
        if known is not None and known[0] is build:
            return known[1]  # YearBuild は変わらないので、前に合った節はまた合う
        for keys, table in self.rounds.get(r, {}).values():
            vk = self._value_key(build, keys)
            if vk is None:
                continue
            for node in table.get(vk, ()):
                if node.matches(build):
                    self.by_build[(r, id(build))] = (build, node)
                    return node
        return None

    def add(self, r: int, build: YearBuild, node: _RoundNode) -> None:
        self.by_build[(r, id(build))] = (build, node)
        families = self.rounds.setdefault(r, {})
        family = families.get(node.traced)
        if family is None:
            family = families[node.traced] = (node.keys(), {})
        vk = self._value_key(build, family[0])
        assert vk is not None
        family[1].setdefault(vk, []).append(node)


def _used_variables(graph: Mapping[tuple[str, str], TraceEntry], names: Iterable[str]) -> frozenset[str]:
    """names の変数（全部の期間）と、トレースでそれが依存した変数の名前。"""
    wanted = set(names)
    stack = [k for k in graph if k[0] in wanted]
    seen: set[tuple[str, str]] = set()
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        entry = graph.get(k)
        if entry is not None:
            stack.extend(entry.children)
    return frozenset(k[0] for k in seen) | wanted


@dataclass
class _ValuePlan:
    """値1つ（変数, 人）の候補の評価（2026-11-12 の4回目：値ごとに、依存する分かれ目だけで組合せを全部評価する）。

    - slots：その値が依存する分かれ目（分かれ目の並びの順。_evaluate_unit が計算の過程から決める）。
    - runs：slots の候補の直積の全部の組の評価（ほかの分かれ目は最初の候補）。上限を超えたら最初の候補の組（基準の評価）だけ。
    - over：直積が上限を超えたとき（計算しない。未確定と、何を入力すれば決まるか）。
    - affected：分かれ目 → その分かれ目だけが違う2つの評価で値・対象外・グループの組み方が変わった入力（ビットか (変数, 人) の集まり）。
      値の入力と重なる分かれ目が「関係する分かれ目」（結果の evaluated）になる（以前の _affected_inputs と同じ意味）。
    """

    slots: list[Slot]
    runs: list[_Run]
    over: TooManyCandidates | None = None
    affected: Mapping[str, Any] = field(default_factory=dict)


def _group_members(build: YearBuild) -> dict[str, dict[str, tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]]]:
    """グループ → 人 → その人が入るインスタンス（ID と役割）。"""
    cached = build.__dict__.get("_group_members")
    if cached is None:
        cached = {}
        for g, insts in build.groups.items():
            m: dict[str, tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = {}
            for inst in insts:
                shape = (inst.id, tuple(sorted((r, tuple(ps)) for r, ps in inst.roles.items())))
                for ps in inst.roles.values():
                    for q in ps:
                        m[q] = shape
            cached[g] = m
        build.__dict__["_group_members"] = cached
    return cached


#: 作り手（build_inputs・グループの組み立て）を、読んだ分かれ目の直積の全部の組で呼んで、出力ごとに依存する分かれ目を決めるときの
#: 組の数の上限（2026-11-12 の4回目）。作り手の呼び出しは OpenFisca の計算をしない Python の関数で、1回 数ミリ秒〜数十ミリ秒。
#: 超えたら安全側（人ごと）に決める。結果が時間で変わらないように固定の値にする（候補の評価の上限 MAX_ASSIGNMENTS とは別）。
PRODUCER_ASSIGNMENTS = 1024


def _producer_dependencies(
    call: Any,
    first: Iterable[Slot],
    slot_of: Mapping[str, Slot],
    order: Any,
    limit: int | None = None,
) -> dict[Any, set[str]] | None:
    """作り手（build_inputs・グループの組み立て）の出力ごとに、その出力が依存する分かれ目を正確に決める（2026-11-12 の4回目）。

    call(候補の組) は（出力, 読んだ分かれ目の ID）を返す。作り手は読んだものの純粋関数なので、読んだ分かれ目の候補の直積の全部の組で
    呼び、1つの分かれ目だけが違う2つの組で出力（_output_diff のキー）が違えば、その出力はその分かれ目に依存する（直積の全部なので、
    2つ以上の分かれ目が同時に変わるときだけ変わる出力も見落とさない）。ある組で新しい分かれ目を読んだら、足して呼び直す
    （読まない分かれ目は、ほかを同じにして変えても、作り手は同じ道を通るので出力を変えない）。直積が limit（既定 PRODUCER_ASSIGNMENTS）
    を超えたら None（呼び出し側が安全側に決める）。order は分かれ目の ID → 並びの番号。
    """
    lim = PRODUCER_ASSIGNMENTS if limit is None else limit
    reads_r = {s.id for s in first}
    while True:
        slots_r = sorted((slot_of[sid] for sid in reads_r), key=lambda s: order(s.id))
        count = 1
        for s_ in slots_r:
            count *= len(s_.candidates)
        if count > lim:
            return None
        outs: dict[tuple[str, ...], Any] = {}
        new: set[str] = set()
        for comb in assignments(slots_r, lim):
            out, read = call(comb)
            outs[tuple(c.label for c in comb.values())] = out
            new |= set(read) - reads_r
        if new:
            reads_r |= new
            continue
        result: dict[Any, set[str]] = {}
        for labels, res in outs.items():
            for i, s_ in enumerate(slots_r):
                for cand in s_.candidates:
                    if cand.label <= labels[i]:
                        continue  # 2つの組の対は1回だけ比べる（小さい名前の側から）
                    other = outs[labels[:i] + (cand.label,) + labels[i + 1:]]
                    for k in _output_diff(res, other):
                        result.setdefault(k, set()).add(s_.id)
        return result


def _output_person(k: Any) -> str:
    """_output_diff のキーの人：("v"・"e", (変数, 人))、("p", 人)、("g", 人)。"""
    return k[1][1] if k[0] in ("v", "e") else k[1]


def _producer_dependencies_by_person(
    call: Any,
    first: Iterable[Slot],
    slot_of: Mapping[str, Slot],
    order: Any,
    people: Iterable[str],
    limit: int | None = None,
) -> dict[Any, set[str]] | None:
    """読んだ分かれ目の直積が上限を超える build_inputs の出力ごとの依存を、人ごとに正確に決める（2026-11-13。B1 の直し）。

    build_inputs は人ごとに書き、人 q の出力は、関係する人（Slot.persons）に q を含む分かれ目と人に結びつかない分かれ目だけに依存する
    （宣言の約束。安全側の決め方 causal_deps と同じ約束で、_resolve_dependencies の説明の 3 が、評価した組の中で確かめる）。
    そこで人 q ごとに、q に関係する分かれ目だけの候補の直積の全部の組で作り手を呼び（ほかの分かれ目は呼び出し側の組のまま。約束のもとで
    q の出力を変えない）、1つの分かれ目だけが違う2つの組で q の出力（_output_diff のキーのうち人が q のもの）が違えば、その出力は
    その分かれ目に依存する。ある組で新しい分かれ目を読んだら、足して全員をやり直す。

    以前は、直積が上限を超えると causal_deps（それを書いた時点までに読んだ全部の分かれ目）だけだったので、人 q の入力のうち市町村の
    注入データと関係のないもの（繰越控除の記録など）まで、q の市町村の候補に依存した。家族が複数の市町村に住むと、人をまたぐ値が家族の
    全部の市町村の候補に依存して、候補の組合せの上限を超えた（docs/measurements/20261113_family-run_findings.md の B1）。
    人ごとの直積の合計が limit（既定 PRODUCER_ASSIGNMENTS）を超えたら None（呼び出し側が causal_deps にする）。
    """
    lim = PRODUCER_ASSIGNMENTS if limit is None else limit
    persons = sorted(set(people))
    known = frozenset(persons)
    reads_r = {s.id for s in first}
    while True:
        result: dict[Any, set[str]] = {}
        new: set[str] = set()
        total = 0
        for q in persons:
            slots_q = sorted(
                (slot_of[sid] for sid in reads_r if not slot_of[sid].persons or q in slot_of[sid].persons), key=lambda s: order(s.id)
            )
            count = 1
            for s_ in slots_q:
                count *= len(s_.candidates)
            total += count
            if total > lim:
                return None
            outs: dict[tuple[str, ...], Any] = {}
            for comb in assignments(slots_q, lim):
                out, read = call(comb)
                outs[tuple(c.label for c in comb.values())] = out
                new |= set(read) - reads_r
            if new:
                break
            for labels, res in outs.items():
                for i, s_ in enumerate(slots_q):
                    for cand in s_.candidates:
                        if cand.label <= labels[i]:
                            continue  # 2つの組の対は1回だけ比べる（小さい名前の側から）
                        other = outs[labels[:i] + (cand.label,) + labels[i + 1:]]
                        for k in _output_diff(res, other):
                            who = _output_person(k)
                            if who == q:
                                result.setdefault(k, set()).add(s_.id)
                            elif who not in known:
                                return None  # people にない人の出力が変わった（人ごとに決められない）：呼び出し側が安全側にする
        if not new:
            return result
        reads_r |= new


class _AsmSig:
    """値を集めたときの situation と対象外（検出の分を含む）。_assemble の reuse で、2つの集め方の違う入力を求めるのに使う。"""

    __slots__ = ("build", "excl")

    def __init__(self, build: YearBuild, excl: frozenset[Exclusion]) -> None:
        self.build = build
        self.excl = excl


def _changed_mask(reuse: dict[str, Any], a: _AsmSig, b: _AsmSig, ix: _InputIndex) -> int:
    """2つの集め方で違うもの（モジュールの入力の部分・段の出力・グループ・対象外）のビット。違えば、それに依存した値は使い回さない。

    モジュールの入力の部分・段の出力・グループのインスタンスは、同じオブジェクトでなければ違うとみなす（安全側。build_year は材料が
    同じなら同じオブジェクトを返す）。人の対象外が違えば、その人の全部の入力。situation の組ごとに1回だけ求める。
    """
    if a is b:
        return 0
    masks = reuse.setdefault("masks", {})
    key = (id(a), id(b))
    hit = masks.get(key)
    if hit is not None and hit[0] is a and hit[1] is b:
        return hit[2]
    bit_of = ix.of

    def person_bits(q: str) -> int:
        out = 0
        for i, k in enumerate(ix.keys):
            if k[1] == q:
                out |= 1 << i
        return out

    m = 0
    x, y = a.build, b.build
    if x is not y:
        pa, sa = _input_parts(x)
        pb, sb = _input_parts(y)
        if len(pa) != len(pb) or x.persons != y.persons:
            m = -1
        else:
            mbits = reuse.setdefault("module_bits", {})
            for i, (u, v) in enumerate(zip(pa, pb)):
                if u is not v:
                    mb = mbits.get(i)
                    if mb is None:
                        mb = 0
                        for k in u:
                            mb |= bit_of(k)
                        mbits[i] = mb
                    m |= mb
            if sa is not sb:
                for k in set(sa) | set(sb):
                    if sa.get(k) is not sb.get(k):
                        m |= bit_of(k)
            for g in set(x.groups) | set(y.groups):
                if x.groups.get(g) is not y.groups.get(g):
                    for q in x.persons:
                        m |= bit_of((f"group:{g}", q))
    if m != -1 and a.excl is not b.excl:
        for e in a.excl ^ b.excl:
            m |= bit_of((e.variable, e.person)) if e.variable is not None else person_bits(e.person)
    masks[key] = (a, b, m)
    return m


class _StageValuesOnly:
    """段の値だけを持つ StageState の代わり（evaluate の context_for が values だけを読む）。"""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self.values = values


def _output_diff(a: Any, b: Any) -> list[Any]:
    """作り手の2つの出力（build_inputs の ModuleInputs か、グループのインスタンスの並び）で違う出力のキー。

    ("v", (変数, 人))：入力の値と由来、("e", (変数, 人))：入力・途中の変数の対象外、("p", 人)：人の対象外、("g", グループ, 人)：インスタンス。
    """
    if a is b:
        return []
    out: list[Any] = []
    if isinstance(a, tuple):  # グループのインスタンスの並び
        def members(insts: Any) -> dict[str, Any]:
            m: dict[str, Any] = {}
            for inst in insts:
                shape = (inst.id, tuple(sorted((r, tuple(ps)) for r, ps in inst.roles.items())), inst.record_ids, inst.states, inst.uses)
                for ps in inst.roles.values():
                    for q in ps:
                        m[q] = shape
            return m

        ma, mb = members(a), members(b)
        return [("g", q) for q in sorted(set(ma) | set(mb)) if ma.get(q) != mb.get(q)]
    av, bv = a.values, b.values
    for k in sorted(set(av) | set(bv)):
        x, y = av.get(k), bv.get(k)
        if x is not y and x != y:
            out.append(("v", k))

    def excl(mi: Any) -> dict[Any, frozenset[Any]]:
        d: dict[Any, set[Any]] = {}
        for e in mi.exclusions:
            d.setdefault((e.variable, e.person), set()).add(e.reason)
        return {k: frozenset(v) for k, v in d.items()}

    ea, eb = excl(a), excl(b)
    for var, person in sorted(set(ea) | set(eb), key=lambda k: (k[0] or "", k[1])):
        if ea.get((var, person)) != eb.get((var, person)):
            out.append(("e", (var, person)) if var is not None else ("p", person))
    return out


def _check_target_candidates(reg: Registry) -> tuple[frozenset[str], ...]:
    """計算の後の検出（RuleModule.checks。_assemble の並び）ごとに、検出が対象外にしうる変数の名前の候補（登録ごとに1回）。

    検出のコード（入れ子の関数を含む）の文字列の定数、コードが参照するモジュールの定数（文字列の tuple・list・set・dict）、呼ぶ規則モジュールの
    関数のそれと同じものから、検出のモジュールの変数の名前を集める（読む変数の名前も入る：多めにとる。2026-11-12 の時点で、検出が
    対象外にする変数は、どれも検出のモジュールの変数を名前で書いている）。名前を組み立てる検出・ほかのモジュールの変数を対象外にする
    検出は見落とすので、_resolve_dependencies が、対象外にした変数がこの候補になければ、その変数と検出のモジュールの変数の全部を足す。
    """
    cache = memo(reg, "check_target_candidates")
    if "all" not in cache:
        names = reg.variable_module

        def strings(fn: Any, seen: set[int]) -> set[str]:
            out: set[str] = set()
            if id(fn) in seen or getattr(fn, "__code__", None) is None:
                return out
            seen.add(id(fn))
            g = getattr(fn, "__globals__", {})
            stack = [fn.__code__]
            while stack:
                code = stack.pop()
                for k in code.co_consts:
                    if isinstance(k, str):
                        out.add(k)
                    elif isinstance(k, (tuple, frozenset)):
                        out |= {x for x in k if isinstance(x, str)}
                    elif hasattr(k, "co_consts"):
                        stack.append(k)
                for n in code.co_names:
                    obj = g.get(n)
                    if isinstance(obj, (tuple, list, set, frozenset)):
                        out |= {x for x in obj if isinstance(x, str)}
                    elif isinstance(obj, dict):
                        out |= {x for x in [*obj.keys(), *obj.values()] if isinstance(x, str)}
                    elif callable(obj) and getattr(obj, "__module__", "").startswith(__package__ + ".rules"):
                        out |= strings(obj, seen)
            return out

        cache["all"] = tuple(
            frozenset(x for x in strings(c, set()) if names.get(x) == m.name) for m in reg.modules for c in m.checks
        )
    return cache["all"]


def _output_bit(k: Any, bit_of: Any, person_bits: Any, group: str | None = None) -> int:
    """_output_diff のキーの入力のビット：入力・対象外は (変数, 人)、人の対象外はその人の全部、グループは ("group:<グループ>", 人)。"""
    kind = k[0]
    if kind in ("v", "e"):
        return bit_of(k[1])
    if kind == "g":
        assert group is not None
        return bit_of((f"group:{group}", k[1]))
    return person_bits(k[1])


def _value_signature(build: YearBuild, i: int, part: Mapping[tuple[str, str], InputValue]) -> dict[tuple[str, str], tuple[type, Any]]:
    """入力の部分の (変数, 人) →（値の型, 値）（_diff_bits が部分をまとめて比べる。situation ごと・部分ごとに1回）。"""
    cache = build.__dict__.setdefault("_value_signatures", {})
    hit = cache.get(i)
    if hit is None or hit[0] is not part:
        hit = cache[i] = (part, {k: (type(iv.value), iv.value) for k, iv in part.items()})
    return hit[1]


def _diff_bits(a: YearBuild, b: YearBuild, index: _InputIndex, person_bits: Any) -> int:
    """2つの situation で値（型と値）・対象外の検出・グループのインスタンスが変わる入力（変数, 人）とグループ（"group:<グループ>", 人）のビット。

    人の対象外の検出が変わるときは、その人の全部（person_bits(人)）。以前の _diff_builds と同じ比べ方（グループは人ごとにした）。
    """
    if a is b:
        return 0
    bit_of = index.of
    bits = 0
    old_parts, old_stage = _input_parts(a)
    new_parts, new_stage = _input_parts(b)
    if len(old_parts) == len(new_parts):
        pairs = [(i, x, y) for i, (x, y) in enumerate(zip(old_parts, new_parts)) if x is not y] + [(-1, old_stage, new_stage)]
    else:
        pairs = [(-2, a.inputs, b.inputs)]
    for i, o, n in pairs:
        if o is n:
            continue
        if _value_signature(a, i, o) == _value_signature(b, i, n):
            continue  # 全部のキーで型と値が同じ（下の比べ方で違いがない。ワーカーの situation は同じオブジェクトにならないので、まとめて比べる）
        for k in sorted(set(o) | set(n)):
            x, y = o.get(k), n.get(k)
            if x is y:
                continue
            if x is None or y is None or type(x.value) is not type(y.value) or x.value != y.value:
                bits |= bit_of(k)
    ea, eb = _exclusion_map(a), _exclusion_map(b)
    for var, person in sorted(set(ea) | set(eb), key=lambda k: (k[0] or "", k[1])):
        if ea.get((var, person)) != eb.get((var, person)):
            bits |= bit_of((var, person)) if var is not None else person_bits(person)
    ga, gb = _group_members(a), _group_members(b)
    for g in sorted(set(ga) | set(gb)):
        ma, mb = ga.get(g, {}), gb.get(g, {})
        for q in sorted(set(ma) | set(mb)):
            if ma.get(q) != mb.get(q):
                bits |= bit_of((f"group:{g}", q))
    return bits


class _PendingStage(Exception):
    """計算の後の検出が、まだ計算していない段の出力に依存する変数を読んだ（その回の検出は飛ばす）。"""


def _stage_values(
    run: _Run,
    stage: Any,
    year: int,
    reg: Registry,
    value_id: Any = None,
    selected: frozenset[str] | None = None,
    extra_specs: Iterable[OutputSpec] = (),
    index: _InputIndex | None = None,
) -> dict[tuple[str, str], StageValue]:
    """段の reads の変数の、全員の値と由来。value_id は（概念 ID, 人）→ 値の ID（省略は所得税の年分の ID）、
    selected は結果に出す出力の変数（省略は全部の出力。出さない出力を読んだときは、その値が依存した値の ID を使う）。
    index は値を集めたときの入力の番号（省略は run.index。_Raw.inputs がビットのとき、StageValue.inputs は frozenset に戻す）。"""
    assert run.sim is not None
    out: dict[tuple[str, str], StageValue] = {}
    ix = index if index is not None else run.index
    specs = {s.variable: s for s in reg.outputs}
    for r_specs in reg.stages.read_specs:
        specs.update({s.variable: s for s in r_specs})
    specs.update({s.variable: s for s in extra_specs if s.variable not in specs})
    is_output = {s.variable for s in reg.outputs} if selected is None else set(selected)
    vid = value_id if value_id is not None else (lambda c, p: _value_id(year, p, c))
    # 値の ID → (変数, 人)：結果に出さない出力を読んだときだけ要る。同じ回の段どうしで1回だけ作る（run.raws は回の中で変わらない）
    id_cache = run.__dict__.setdefault("_id_to_key", {})
    id_key = (value_id, extra_specs if isinstance(extra_specs, tuple) else None)
    id_to_key: dict[str, tuple[str, str]] = {}

    def resolve(ids: Iterable[str]) -> tuple[str, ...]:
        nonlocal id_to_key
        if not id_to_key:
            hit = id_cache.get(id_key) if id_key[1] is not None else None
            if hit is None:
                hit = {vid(specs[v].concept, p): (v, p) for (v, p) in run.raws if v in specs}
                if id_key[1] is not None:
                    id_cache[id_key] = hit
            id_to_key = hit
        # 結果に出さない出力の値の ID は、その値が依存した値の ID に置き換える（結果に出す値に届くまで）。
        # 以前は1段だけ置き換え、判定日の単位で所得税の出さない出力の ID が残って ScenarioResult が失敗していた（2026-11-12）
        out: set[str] = set()
        stack = list(ids)
        seen: set[str] = set()
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            seen.add(i)
            key = id_to_key.get(i)
            if key is None or key[0] in is_output:
                out.add(i)
            else:
                stack.extend(run.raws[key].deps)
        return tuple(sorted(out))

    for var in stage.reads:
        spec = specs[var]
        arr = run.sim.cache[var]
        for idx, pid in enumerate(run.build.persons):
            raw = run.raws[(var, pid)]
            value_ids = (vid(spec.concept, pid),) if var in is_output else resolve(raw.deps)
            out[(var, pid)] = StageValue(
                variable=var,
                person=pid,
                value=_to_python(arr[idx], spec.value_type),
                states=frozenset(raw.states),
                facts=tuple(sorted(raw.facts)),
                value_ids=value_ids,
                reasons=tuple(raw.reasons),
                basis=tuple(raw.basis),
                inputs=ix.to_set(raw.inputs) if isinstance(raw.inputs, int) else raw.inputs,
                missing=tuple(raw.missing[k] for k in sorted(raw.missing)),
                extra=ix.to_set(raw.extra) if raw.extra else frozenset(),
            )
    return out


#: 値の ID の時点の部分が判定日のもの（判定日の単位の見え方で、ほかの時点の ID に判定日を前に付けるのに使う）
_DATE_TAG = re.compile(r"^v:\d{4}-\d{2}-\d{2}:")


def _view_id(value_id: str, on: _dt.date) -> str:
    """結果の値の ID を、判定日の単位 on の見え方に直す（Unit.tag と同じ形：判定日でない値は "v:<判定日>@<時点>:…"）。"""
    if _DATE_TAG.match(value_id):
        return value_id
    if not value_id.startswith("v:"):
        raise ValueError(f"値の ID の形でない: {value_id}")
    return f"v:{on.isoformat()}@{value_id[2:]}"


def _as_view(v: ResultValue, on: _dt.date) -> ResultValue:
    return replace(v, id=_view_id(v.id, on), depends_on=tuple(sorted(_view_id(x, on) for x in v.depends_on)))


def _evaluate_unit(
    ir: Mapping[str, Any],
    unit: Unit,
    system: OkuraTaxBenefitSystem,
    reg: Registry,
    scope: InputScope,
    filing_date: FilingDate | None = None,
    injected: InjectedData | None = None,
    extra_specs: tuple[OutputSpec, ...] = (),
    engine: _Engine | None = None,
    views: tuple[Unit, ...] | None = None,
    dispatch: _parallel.Dispatcher | None = None,
    handle: bool = False,
) -> Any:
    """評価の単位1つ（所得の年分 unit.income_year の situation。判定日の単位は判定日ごと）を評価する。

    dispatch（2026-11-12 の5回目）：候補の組をワーカーのプロセスで計算する割り振り（parallel.Dispatcher。None なら直列）。
    handle：ワーカーが使う。単位を組み立てたところで _UnitHandle を返す（基準の組を計算しない）。

    返すもの：結果の値（問いが求めた値と、その依存先）、境目の説明、対象外の項目、問いが求めた値の ID。

    views（2026-11-12 の4回目）：同じ situation で答える単位の並び（所得税の年分の単位と、同じ年の判定日の単位）。unit はその窓口を
    合わせたもの（on は None）で、1回だけ評価して、単位ごとに上の4つを返す（判定日の単位の値の ID は Unit.tag の形に直す）。
    判定日の単位を別に評価すると、所得税の全部の値と段階評価をもう一度計算していた（docs/measurements/20261112_core-perf_before-after.md §7.3）。
    extra_specs（欄が読む途中の概念）は views の最初の単位の問いにだけ足す。

    候補の評価（D21 R6。2026-11-12 の4回目に作り直した）：値ごとに、その値が依存する分かれ目だけで組合せを全部評価する。
    依存する分かれ目は計算の過程から決める（_ValuePlan・下の説明）。依存する分かれ目だけで組合せが上限を超える値は計算せず、
    未確定と「何を入力すれば決まるか」（依存する分かれ目）を返す。以前の、上限を超えた人のつながりで分かれ目を1つずつ動かして
    比べる近似（_affected_inputs）は、2つ以上の分かれ目が同時に変わったときだけ変わる値を見落としうるのでやめた。
    """
    view_units = (unit,) if views is None else tuple(views)
    year = unit.income_year
    planned = [unit_outputs(reg, v) for v in view_units]
    selected_vars = frozenset(s.variable for specs_v, _ in planned for s in specs_v)
    specs: tuple[OutputSpec, ...] = tuple(o for o in reg.outputs if o.variable in selected_vars)
    view_asked = [asked for _, asked in planned]
    if extra_specs:
        # 欄が読む途中の概念（forms_output.form_specs）：出力の後ろに足す。トレースを止める出力の集まりには入れない（ほかの値は変わらない）
        extra = tuple(e for e in extra_specs if e.variable not in selected_vars)
        specs = specs + extra
        view_asked[0] = view_asked[0] | frozenset(e.variable for e in extra)
    value_id = _id_function(unit, reg.dictionary)
    time_of = _time_function(unit, reg.dictionary)
    alive = tuple(p["id"] for p in ir["persons"] if alive_in_year(p, year))
    items = not_alive_items(ir, year, frozenset(alive))
    if not alive or not specs:
        empty = [([], [], items, frozenset()) for _ in view_units]
        return empty[0] if views is None else empty
    window = YearWindow(
        parameters_at=system.get_parameters_at_instant,
        parameter_root=system.parameters,
        filing_date=filing_date,
        variable_default=lambda v: system.variables[v].default_value,
        windows=unit.windows,
        injected=injected,
    )
    base = YearContext(ir, year, alive, window=window)
    decisions = resolve_decisions(base, reg)
    lazy_keys = {decisions.slot_keys[s.id]: s.id for s in decisions.lazy}
    r_slots = rounding_slots(reg)
    person_excl = [Exclusion(p, r) for p, r in residency_exclusions(ir, year, reg).items()]
    period = str(year)
    plan = reg.stages
    rounding_vars = {spec.variable: s.id for s, spec in r_slots if spec.variable is not None}
    rounding_names = {spec.name: s.id for s, spec in r_slots}
    incomplete = scope.incomplete_income(year)
    zero_idx = _zero_index(reg, ir, year)
    bmemo: dict[Any, list[Any]] = {}  # build_inputs・グループの組み立ての使い回し（situation._reuse）
    unit_index = _InputIndex()  # 値の入力の集まりのビットの番号（単位の全部の計算で共有する）
    xp = cross_person_edges(reg.dictionary)
    final_vars = tuple(s.variable for s in specs)

    # 分かれ目：未入力の判断・選択（と候補のある未注入の1か所）、読んだときだけ開く1か所、根拠のない端数・法令の読みの候補（この並びが結果の並び）
    slot_order: list[Slot] = list(decisions.open) + list(decisions.lazy) + [s for s, _ in r_slots]
    slot_of = {s.id: s for s in slot_order}
    order_ix = {s.id: i for i, s in enumerate(slot_order)}
    default_label = {s.id: s.candidates[0].label for s in slot_order}
    # 読んだ1か所 (種類, key) → 分かれ目の ID（単調な判断の群は、群の1か所の全部が群の分かれ目。端数・読みは種類 ""）
    read_sid: dict[tuple[str, str], str] = {key: sid for sid, key in decisions.slot_keys.items()}
    for sid, members in decisions.monotone_members.items():
        for key, _ in members:
            read_sid[key] = sid
    for s, spec in r_slots:
        read_sid[("", spec.name)] = s.id

    def full(a: Assignment) -> dict[str, Any]:
        # 組にない判断・選択の分かれ目は最初の候補にする
        return {**{s.id: s.candidates[0] for s in decisions.open}, **{s.id: s.candidates[0] for s in decisions.lazy}, **a}

    def rounding_of(a: Assignment) -> tuple[dict[str, str], dict[str, str]]:
        # 組にない端数の候補は最初の候補にする
        by_var: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for s, spec in r_slots:
            v = a[s.id].value if s.id in a else s.candidates[0].value
            if spec.variable is not None:
                by_var[spec.variable] = v
            by_name[spec.name] = v
        return by_var, by_name

    def context_for(a: Assignment, state: StageState | None) -> tuple[YearContext, set[str], dict[str, str], set[str]]:
        a = full(a)
        decided: dict[tuple[str, str], Decided] = dict(decisions.fixed)
        for sid, cand in a.items():
            if sid in decisions.slot_keys:
                decided[decisions.slot_keys[sid]] = Decided(cand.value, (), frozenset(), open=True)
            elif sid in decisions.monotone_members:
                for key, member_cands in decisions.monotone_members[sid]:
                    decided[key] = Decided(member_cands[cand.value].value, (), frozenset(), open=True)
        by_var, by_name = rounding_of(a)
        reads: set[str] = set()
        dreads: set[str] = set()
        win = replace(
            window, rounding=by_name, rounding_reads=reads, stage_values=state.values if state is not None else {},
            lazy_decisions=lazy_keys, decision_reads=dreads,
        )
        return base.with_decided(decided, window=win), reads, by_var, dreads

    def read_ids(names: Iterable[str]) -> frozenset[str]:
        return frozenset(rounding_names[n] for n in names if n in rounding_names)

    def collect_reads(acc: dict[Any, set[tuple[str, str]]], build: YearBuild) -> None:
        for producer, entries in build.__dict__.get("_reads", {}).items():
            acc.setdefault(producer, set()).update(entries)

    # 段の回の使い回し（_RoundNode）：回の番号 → その回を計算した節（段に渡す値が同じになる situation の条件つき）
    rounds_memo = _RoundMemo()
    asm_reuse: dict[str, Any] = {}  # 集めた値の使い回し（_assemble の reuse）
    # 段の関数の出力の使い回し（situation.apply_stage の memo：同じ節の値と、同じ読んだ判断なら同じ出力のオブジェクト）
    smemo: dict[Any, list[Any]] = {}

    def run_stages(
        a: Assignment,
        engine: _Engine | None,
        late: Mapping[str, Mapping[tuple[str, str], StageValue]] | None,
        acc: dict[Any, set[tuple[str, str]]],
        builds: list[tuple[Mapping[str, Any], YearBuild]],
    ) -> tuple[StageState, set[str], list[tuple[str, Any]], dict[str, list[StageValue]]]:
        """候補の組1つの段階評価の全部の段（最後の計算の前まで）。段の状態・読んだ端数の候補・段の読んだ値・段が late で読んだ値。

        late は段の名前 → StageSpec.late_reads の値（不動点の繰り返しで前の最後の計算の値を渡す。なければ pending）。
        acc に、回の situation の作り手が読んだ1か所を足し、builds に回の（段の値の写し, situation）を足す（値ごとの候補の評価）。
        """
        state = StageState()
        reads: set[str] = set()
        checks: list[tuple[str, Any]] = []
        late_log: dict[str, list[StageValue]] = {}
        for r in range(plan.rounds):
            ctx, round_reads, by_var, dreads = context_for(a, state)
            build = build_year(ctx, reg, by_var, scope.touched, person_excl, state, bmemo)
            collect_reads(acc, build)
            builds.append((dict(state.values), build))  # 段の値は後の回で足されるので、この回の写し
            node = rounds_memo.find(r, build)
            if node is None:
                variables = [v for stage in plan.ranks[r] for v in stage.reads]
                sim = _simulate(build, system, reg, period, rounding_vars, variables, engine)
                run = _Run(a, build, sim)
                targets = _round_targets(plan, r, sim, reg, year)
                requested: set[str] = set(variables)
                _assemble(
                    run, ir, year, system, reg, incomplete, xp,
                    track_inputs=True, targets=targets, pending=plan.pending[r], filing_date=filing_date, value_id=value_id,
                    needed_from=variables, zero_index=zero_idx, requested=requested, index=unit_index, reuse=asm_reuse,
                )
                stage_values = {stage.name: _stage_values(run, stage, year, reg, value_id, selected_vars) for stage in plan.ranks[r]}
                round_checks = {stage.name: tuple((v, sim.cache[v]) for v in stage.reads) for stage in plan.ranks[r]}
                # 使い回しの条件：この回の段に渡す値（段の読む値・集めた値・検出・集め忘れの検出・根拠が引いたもの）が
                # トレースで依存した変数の入力
                node = _RoundNode(_used_variables(sim.graph(), requested), build, stage_values, round_checks, sim.read_rounding)
                rounds_memo.add(r, build, node)
            for stage in plan.ranks[r]:
                checks += node.checks[stage.name]
                used = apply_stage(stage, ctx, node.values[stage.name], state, (late or {}).get(stage.name), smemo)
                if used:
                    late_log[stage.name] = used
            reads |= set(read_ids(round_reads)) | set(node.read_rounding) | dreads  # 段の関数が読んだ端数の候補・読んだときだけ開く1か所も含む
        return state, reads, checks, late_log

    def late_values(a: Assignment, build: YearBuild, final: _Sim) -> dict[tuple[str, str], StageValue]:
        """最後の計算での、段の late_reads の変数の全員の値（段が読む形。_stage_values と同じ由来）。"""
        run = _Run(a, build, final)
        late_vars = [s.variable for s in plan.late_specs]
        for v in late_vars:
            if v not in final.cache:
                final.cache[v] = final.sim.calculate(v, _period(period))
        graph_targets = _round_targets_final(final, reg, year, plan.late_specs)
        _assemble(
            run, ir, year, system, reg, incomplete, xp,
            track_inputs=True, targets=graph_targets, filing_date=filing_date, value_id=value_id,
            needed_from=late_vars, zero_index=zero_idx, index=unit_index, reuse=asm_reuse,
        )
        probe = StageSpec(name="（late_reads の値）", title="", reads=tuple(late_vars))
        return _stage_values(run, probe, year, reg, value_id, selected_vars, extra_specs=plan.late_specs)

    def converge(
        a: Assignment, acc: dict[Any, set[tuple[str, str]]], builds: list[tuple[Mapping[str, Any], YearBuild]]
    ) -> tuple[StageState, set[str], list[tuple[str, Any]], YearBuild, _Sim, set[str]]:
        """段階評価の全部の段と最後の計算（段の late_reads の不動点の繰り返しを含む。StageSpec.late_reads）。

        段が late で読んだ値が、最後の計算の値と同じ（pending でない）になるまで、最後の計算の値を渡して段を計算し直す。
        MAX_FIXPOINT 回で収束しなければ、pending の値でもう一度計算する（段は pending のときの安全側の扱いをする）。
        返すもの：段の状態・読んだ端数の候補（段の回）・段の読んだ値・最後の situation・最後の計算・最後の situation で読んだ端数の候補と1か所。
        acc に、全部の situation の作り手と段の関数が読んだ1か所を足す（繰り返しの全部の回の和）。
        """
        late: dict[str, dict[tuple[str, str], StageValue]] = {}
        attempt = 0
        while True:
            state, reads, checks, late_log = run_stages(a, engine, late, acc, builds)
            for name, entries in state.reads.items():
                acc.setdefault(("stage", name), set()).update(entries)
            ctx, round_reads, by_var, dreads = context_for(a, state)
            build = build_year(ctx, reg, by_var, scope.touched, person_excl, state, bmemo)
            collect_reads(acc, build)
            builds.append((dict(state.values), build))
            extra = set(read_ids(round_reads)) | dreads
            final = _simulate(build, system, reg, period, rounding_vars, final_vars, engine)
            if not late_log or attempt >= MAX_FIXPOINT:  # 後者：収束しなかったので pending の値で計算し直した結果
                return state, reads, checks, build, final, extra
            now = late_values(a, build, final)
            if all(not v.pending and now.get((v.variable, v.person)) == v for used in late_log.values() for v in used):
                return state, reads, checks, build, final, extra
            attempt += 1
            # 収束しなければ、最後は pending の値で計算し直す（段の安全側の扱い）
            late = {name: now for name in late_log} if attempt < MAX_FIXPOINT else {}

    modules_by_name = {m.name: m for m in reg.modules}
    rounding_name_of = {s.id: spec.name for s, spec in r_slots}
    exact_cache: dict[Any, list[tuple[tuple[Any, ...], Any]]] = {}

    def variant(a: Assignment, stage_values: Mapping[str, Any], overrides: Mapping[str, Any]) -> YearContext:
        """候補の組 a の situation の作り手の窓口（段の値は stage_values）で、overrides の分かれ目だけを替えたもの。"""
        ctx, _r, _v, _d = context_for({**a, **overrides}, _StageValuesOnly(stage_values))
        return ctx

    def stage_log_matches(log: tuple[Any, ...], stage_values: Mapping[str, Any]) -> bool:
        for stage, var, person, sv in log:
            values = stage_values.get(stage)
            if values is None:
                if not sv.pending:
                    return False
            elif sv.pending:
                return False
            else:
                # 等しい段の値（ワーカーに渡した表・別の回で作り直した値）でもよい：作り手の出力ごとの依存する分かれ目（キーと分かれ目の ID）は、
                # 読んだ段の値の中身の関数で、オブジェクトを持たない（2026-11-12 の5回目。以前は同じオブジェクトのときだけ）
                now = values.get((var, person))
                if now is not sv and now != sv:
                    return False
        return True

    def enumerate_producer(
        key: Any, fn: Any, a: Assignment, stage_values: Mapping[str, Any], first: Iterable[str], by_person: bool = False
    ) -> dict[Any, set[str]] | None:
        """作り手 key（("inputs", モジュール)・("group", モジュール, グループ)）を、読んだ分かれ目の直積の全部の組で呼び、出力ごとに
        値を変える分かれ目（1つの分かれ目だけが違う2つの組で出力が違う分かれ目：直積の全部なので、2つ以上が同時に変わるときだけ
        変わる出力も見落とさない）を返す。読む分かれ目が増えたら増やして呼び直す。直積が PRODUCER_ASSIGNMENTS を超えたら None
        （呼び出し側が安全側にする）。
        作り手は読んだもの（判断・選択・注入の1か所、端数・読みの候補、段の値）の純粋関数なので、結果は読んだ段の値が同じなら同じ。
        by_person（2026-11-13）：直積が上限を超えた build_inputs を、人ごとに、その人に関係する分かれ目だけの直積で決める
        （_producer_dependencies_by_person。ほかの分かれ目は組 a のまま）。
        """
        cache_key = (key, "by_person") if by_person else key
        for log, result in exact_cache.get(cache_key, ()):
            if stage_log_matches(log, stage_values):
                return result
        log: list[Any] = []

        def call(comb: Mapping[str, Any]) -> tuple[Any, set[str]]:
            ctx2 = variant(a, stage_values, comb)
            ctx2.stage_log = []
            sink: dict[Any, Any] = {}
            out = _reuse(None, key, ctx2, fn, sink)  # 表に足さない（評価の表を長くしない）
            log.extend(ctx2.stage_log)
            return out, {read_sid[e] for e in sink.get(key, ()) if e in read_sid}

        if by_person:
            result = _producer_dependencies_by_person(call, [slot_of[sid] for sid in first], slot_of, order_ix.__getitem__, alive)
        else:
            result = _producer_dependencies(call, [slot_of[sid] for sid in first], slot_of, order_ix.__getitem__)
        exact_cache.setdefault(cache_key, []).append((tuple(log), result))
        return result

    causal_cache: dict[int, tuple[Any, dict[str, int]]] = {}

    def causal_deps(
        mi: Any, got: Mapping[tuple[str, str], Any], excl: Iterable[Exclusion], auto: frozenset[str], first: list[str],
        bit_of: Any, person_bits: Any,
    ) -> dict[str, int]:
        """読んだ分かれ目の直積が大きい build_inputs の、安全側の依存（分かれ目 → ビット）。入力・対象外は、それを書いた時点までに読んだ
        1か所（registry.CAPTURE の因果。記録がなければ読んだ全部）のうち、関係する人にその人を含む分かれ目か人に結びつかない分かれ目に
        依存するとする（Slot.persons の宣言の約束。_resolve_dependencies の説明の 3 で確かめる）。"""
        hit = causal_cache.get(id(mi))
        if hit is not None and hit[0] is mi:
            return hit[1]
        order, made = (mi.__dict__.get("_causal") if mi is not None else None) or ((), {})
        cum: list[frozenset[str]] = [frozenset()]
        acc_s: set[str] = set()
        for e in order:
            sid = read_sid.get(e)
            if sid is not None:
                acc_s.add(sid)
            cum.append(frozenset(acc_s))
        everything = frozenset(first)

        def before(obj: Any) -> frozenset[str]:
            rec = made.get(id(obj)) if obj is not None else None
            return cum[rec[1]] if rec is not None and rec[0] is obj else everything

        out: dict[str, int] = {}
        values = mi.values if mi is not None else {}
        for key in got:
            if key[0] in auto:
                continue
            q = key[1]
            for sid in before(values.get(key)):
                ps = slot_of[sid].persons
                if not ps or q in ps:
                    out[sid] = out.get(sid, 0) | bit_of(key)
        for e in excl:
            b = bit_of((e.variable, e.person)) if e.variable is not None else person_bits(e.person)
            for sid in before(e):
                ps = slot_of[sid].persons
                if not ps or e.person in ps:
                    out[sid] = out.get(sid, 0) | b
        causal_cache[id(mi)] = (mi, out)  # mi を持っておく（id を使い回されないように）
        return out

    def exact_deps(run: _Sim, bit_of: Any, person_bits: Any, key_bits: Any) -> dict[str, int]:
        with _COMPUTE:
            return _exact_deps(run, bit_of, person_bits, key_bits)

    def _exact_deps(run: _Sim, bit_of: Any, person_bits: Any, key_bits: Any) -> dict[str, int]:
        """候補の組1つの評価の全部の situation（段の回と最後）で、モジュールの入力・対象外とグループのインスタンスが依存する分かれ目
        （分かれ目 → ビット）。作り手が読んだ分かれ目の直積が上限以内なら作り手を直積の全部で呼んで出力ごとに正確に決め
        （enumerate_producer）、超えたら安全側にする（build_inputs は人ごとに書くので、人 q の出力は関係する人に q を含む分かれ目と
        人に結びつかない分かれ目に依存する。グループは読んだ全部の分かれ目に依存する）。"""
        out: dict[str, int] = {}

        def add(sid: str, b: int) -> None:
            if b:
                out[sid] = out.get(sid, 0) | b

        a, builds = run.__dict__["builds"]
        for stage_values, build in builds:
            reads = build.__dict__.get("_reads", {})
            for mname, got, excl, auto, _stage_reads, mi in build.__dict__.get("_modules", ()):
                first = sorted({read_sid[e] for e in reads.get(("inputs", mname), ()) if e in read_sid})
                if not first:
                    continue
                m = modules_by_name[mname]
                found = enumerate_producer(("inputs", mname), m.build_inputs, a, stage_values, first)
                if found is None:  # 直積が上限を超えた：人ごとに決める（2026-11-13）。それも超えたら安全側（causal_deps）
                    found = enumerate_producer(("inputs", mname), m.build_inputs, a, stage_values, first, by_person=True)
                if found is not None:
                    for k, sids in found.items():
                        b = _output_bit(k, bit_of, person_bits)
                        for sid in sids:
                            add(sid, b)
                    continue
                for sid, b in causal_deps(mi, got, excl, auto, first, bit_of, person_bits).items():
                    add(sid, b)
            for m in reg.modules:
                for g, builder in m.groups.items():
                    first = sorted({read_sid[e] for e in reads.get(("group", m.name, g), ()) if e in read_sid})
                    if not first:
                        continue
                    found = enumerate_producer(("group", m.name, g), lambda c, b_=builder: tuple(b_(c)), a, stage_values, first)
                    if found is not None:
                        for k, sids in found.items():
                            b = _output_bit(k, bit_of, person_bits, g)
                            for sid in sids:
                                add(sid, b)
                        continue
                    b = 0
                    for inst in build.groups.get(g, ()):
                        for ps in inst.roles.values():
                            for q in ps:
                                b |= bit_of((f"group:{g}", q))
                    for sid in first:
                        add(sid, b)
        return out

    track = [bool(decisions.open or decisions.lazy)]  # 入力の依存（_Raw.inputs）を集めるか（分かれ目がありうるときだけ。時間を抑える）

    def staged(a: Assignment, needed: frozenset[str] | None = None) -> _Sim:
        with _COMPUTE:
            return _staged(a, needed)

    def _staged(a: Assignment, needed: frozenset[str] | None = None) -> _Sim:
        """候補の組1つを、段階評価の全部の段と最後の計算まで行い、値を集める（段がなければ最後の計算だけ）。

        Simulation は単位の中で使い回す（_Engine）ので、値はこの計算の直後に集める（_Sim.raws）。needed を渡すと、その変数と、
        それがトレースで依存した出力だけを集める（基準の組でない組は、その組を要る値だけ。値ごとの候補の評価。2026-11-12 の4回目）。
        """
        acc: dict[Any, set[tuple[str, str]]] = {}
        builds: list[tuple[Mapping[str, Any], YearBuild]] = []
        state, reads, checks, build, final, extra = converge(a, acc, builds)
        for var, arr in checks:
            now = final.sim.calculate(var, _period(period))
            if not numpy.array_equal(arr, now):
                raise ValueError(f"段の値と最後の計算の値が違う: {var}（段の依存の宣言の誤り）")
        final.read_rounding = frozenset(reads) | extra | set(final.read_rounding)
        final.state = state
        run = _Run(a, build, final)
        _assemble(
            run, ir, year, system, reg, incomplete, xp,
            track_inputs=track[0], targets=specs, filing_date=filing_date, value_id=value_id, zero_index=zero_idx,
            index=unit_index, check_deps=track[0], needed_from=sorted(needed) if needed is not None else None, reuse=asm_reuse,
        )
        final.raws = run.raws
        final.reads = acc
        final.__dict__["assembled"] = needed
        final.__dict__["builds"] = (a, tuple(builds))
        final.check_bits = run.check_bits
        final.check_targets = run.check_targets
        final.sim = None  # 使い回す Simulation は次の計算で変わる（値は raws と cache に集めた）
        final.engine = None
        return final

    if engine is None:
        engine = _Engine(system)
    runs: dict[tuple[tuple[str, str], ...], _Sim] = {}  # 候補の組（最初の候補でない分かれ目だけ）→ 評価
    new_runs: list[tuple[tuple[str, str], ...]] = []

    def canon(a: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((sid, c.label) for sid, c in a.items() if c.label != default_label[sid]))

    def pending(a: Assignment, needed: frozenset[str] | None) -> tuple[bool, frozenset[str] | None]:
        """組 a を計算するか（まだない、か前に集めなかった値が要る）と、集める値。"""
        run = runs.get(canon(a))
        if run is None:
            return True, needed
        if run.__dict__["assembled"] is not None and (needed is None or not needed <= run.__dict__["assembled"]):
            # 前に集めなかった値が要る：集める値を足して評価し直す（situation は同じ。段の回と Simulation は使い回す）
            return True, None if needed is None else needed | run.__dict__["assembled"]
        return False, needed

    def simulate(a: Assignment, needed: frozenset[str] | None = None) -> _Sim:
        todo, needed = pending(a, needed)
        key = canon(a)
        if todo:
            runs[key] = staged(a, needed)
            new_runs.append(key)
        return runs[key]

    def simulate_many(items: list[tuple[Assignment, frozenset[str] | None]]) -> None:
        """互いに独立な組の並びを計算する（runs・new_runs に並びの順で入れる）。並列のとき（dispatch）はワーカーで計算する
        （結果は直列と同じ。ワーカーが落ちたら親で直列に計算する）。"""
        todo: list[tuple[tuple[tuple[str, str], ...], Assignment, frozenset[str] | None]] = []
        for a, needed in items:
            go, needed = pending(a, needed)
            if go:
                todo.append((canon(a), a, needed))
        if dispatch is not None and todo:
            done = dispatch.run(track[0], [(tuple((sid, c.label) for sid, c in a.items()), needed) for _, a, needed in todo])
            if done is not None:
                for (key, _a, _n), packed in zip(todo, done):
                    runs[key] = _unpack(packed)
                    new_runs.append(key)
                return
        for key, a, needed in todo:
            runs[key] = staged(a, needed)
            new_runs.append(key)

    def compute_base() -> _Sim:
        """基準の組（全部が最初の候補）。端数・読みの候補を読んだら、入力の依存を集めて評価し直す（それまでは分かれ目がないので
        集めなかった）。親とワーカー（_UnitHandle.base）が同じ手順で計算する。"""
        b = simulate({})
        if not track[0] and b.read_rounding:
            track[0] = True
            runs.clear()
            new_runs.clear()
            b = simulate({})
        return b

    if handle:
        # ワーカー（parallel）：単位を組み立てたところまでで返す（基準の組は _UnitHandle.base が計算する）
        return _UnitHandle(
            staged, compute_base, track, slot_of, unit_index, alive, rounding_vars, plan, read_sid, order_ix, exact_deps, exact_cache
        )

    base_run: _Sim | None = None
    if dispatch is not None and len(decisions.open) >= _parallel.MIN_OPEN_SLOTS:
        # 並列：全部のワーカーが基準の組を計算して使い回しの表を温め、親は最初のワーカーの結果を使う（親は計算しない）
        dispatch.attach(unit_index)
        got = dispatch.base()
        if got is not None:
            packed, track[0] = got
            base_run = runs[()] = _unpack(packed)
            new_runs.append(())
    else:
        dispatch = None  # 分かれ目が少ない単位は親で直列に計算する（組が少なく、ワーカーより速い）
    if base_run is None:
        dispatch = None
        base_run = compute_base()

    keys = [(spec.variable, pid) for spec in specs for pid in alive]
    deps_of: dict[tuple[str, str], frozenset[str]] = {k: frozenset() for k in keys}
    over: dict[tuple[str, str], int] = {}
    affected: dict[str, int] = {}  # 分かれ目 → その分かれ目だけが違う評価の組で変わった入力（ビット。_diff_bits）
    if track[0]:
        _resolve_dependencies(
            keys, deps_of, over, affected, runs, new_runs, simulate_many, slot_of, order_ix, default_label, read_sid,
            rounding_vars, plan, reg, unit_index, alive, exact_deps,
        )
    merged: dict[tuple[str, str], ResultValue] = {}
    for spec in specs:
        for pid in alive:
            k = (spec.variable, pid)
            slots_k = sorted((slot_of[sid] for sid in deps_of[k]), key=lambda s: order_ix[s.id])
            if k in over:
                vp = _ValuePlan(slots_k, [_Run({}, base_run.build, base_run, raws=base_run.raws, index=unit_index)],
                                TooManyCandidates(over[k], MAX_ASSIGNMENTS), {})
            else:
                combos = assignments(slots_k)
                vp = _ValuePlan(
                    slots_k,
                    [_Run(a, runs[canon(a)].build, runs[canon(a)], raws=runs[canon(a)].raws or {}, index=unit_index) for a in combos],
                    None,
                    {s.id: affected.get(s.id, 0) for s in slots_k},
                )
            merged[k] = _merge_value(spec, pid, vp, year, value_id, time_of, unit_index)
    values_all = [merged[(spec.variable, pid)] for spec in specs for pid in alive]
    out: list[tuple[list[ResultValue], list[Any], list[OutOfScopeItem], frozenset[str]]] = []
    for view, asked_vars in zip(view_units, view_asked):
        vals = values_all
        if views is not None and view.on is not None and unit.on is None:
            vals = [_as_view(v, view.on) for v in values_all]  # 判定日の単位の値の ID（Unit.tag の形）
        vals, asked_ids = _prune(vals, asked_vars)
        by_key = {(v.variable, v.person): v for v in vals}
        explained: list[Any] = list(_boundaries(by_key, list(alive), view, reg))
        explained += _age_boundaries(by_key, list(alive), view, reg, ir, system)  # 年齢の境目（_evaluate_scenario が分ける）
        out.append((vals, explained, items, asked_ids))
    return out[0] if views is None else out


class _Bits:
    """入力のビットの道具（評価の単位の _InputIndex ごと）：(変数, 人) のビット・人の全部の入力のビット・作り手の出力のビット。

    person(q) は、その時点で番号のある入力のうち人 q のもの（番号の数が変われば作り直す）。依存する分かれ目は、同じ組の値の入力の
    ビットとの重なりだけに使うので、その組の値の入力に番号があれば足りる（ワーカーで求めて親の番号に付け替えても同じ重なり）。
    """

    def __init__(self, index: _InputIndex) -> None:
        self.index = index
        self.of = index.of
        self._pb: dict[str, tuple[int, int]] = {}
        self._kb: dict[int, tuple[Any, dict[str, int], int]] = {}

    def person(self, q: str) -> int:
        keys = self.index.keys
        n = len(keys)
        hit = self._pb.get(q)
        if hit is not None and hit[0] == n:
            return hit[1]
        b = 0
        for i, k in enumerate(keys):
            if k[1] == q:
                b |= 1 << i
        self._pb[q] = (n, b)
        return b

    def key(self, got: Mapping[tuple[str, str], Any], auto: frozenset[str]) -> tuple[dict[str, int], int]:
        hit = self._kb.get(id(got))
        if hit is not None and hit[0] is got:
            return hit[1], hit[2]
        bit_of = self.of
        per: dict[str, int] = {}
        total = 0
        for var, q in got:
            if var in auto:
                continue
            b = bit_of((var, q))
            per[q] = per.get(q, 0) | b
            total |= b
        self._kb[id(got)] = (got, per, total)  # got を持っておく（id を使い回されないように）
        return per, total


def _attribution(
    run: _Sim,
    exact_deps: Any,
    bits: _Bits,
    alive: tuple[str, ...],
    rounding_vars: Mapping[str, str],
    plan: Any,
    read_sid: Mapping[tuple[str, str], str],
    order_ix: Mapping[str, int],
) -> dict[str, int]:
    """候補の組1つの評価の、分かれ目 → その分かれ目に依存する入力・グループ・対象外（ビット）（_resolve_dependencies の説明の 1）。

    作り手の出力（exact_deps）、端数の候補を渡す入力変数、段の関数の出力・グループ・対象外（段が読んだ全部の1か所）。読んだ1か所で決まる。
    親（_resolve_dependencies）とワーカー（_UnitHandle）が同じ関数で求める。
    """
    bit_of, person_bits = bits.of, bits.person
    k: dict[str, int] = dict(exact_deps(run, bit_of, person_bits, bits.key))

    def add(sid: str, b: int) -> None:
        if b:
            k[sid] = k.get(sid, 0) | b

    def sids_of(entries: Iterable[tuple[str, str]]) -> list[str]:
        return sorted({read_sid[e] for e in entries if e in read_sid}, key=order_ix.__getitem__)

    build, st, reads = run.build, run.state, run.reads or {}
    auto_vars = sorted({v for part in build.__dict__.get("_modules", ()) for v in part[3]})
    for var in auto_vars:
        sid = rounding_vars.get(var)
        if sid is not None:
            for q in alive:
                add(sid, bit_of((var, q)))
    if st is not None:
        by_stage: dict[str, int] = {}
        for (var, q) in sorted(st.inputs):
            name = plan.written_variables.get(var)
            if name is not None:
                by_stage[name] = by_stage.get(name, 0) | bit_of((var, q))
        for g, insts in sorted(st.groups.items()):
            name = plan.written_groups.get(g)
            if name is None:
                continue
            for inst in insts:
                for ps in inst.roles.values():
                    for q in ps:
                        by_stage[name] = by_stage.get(name, 0) | bit_of((f"group:{g}", q))
        for name, b in sorted(by_stage.items()):
            for sid in sids_of(reads.get(("stage", name), ())):
                add(sid, b)
        excl_bits = 0
        for e in st.exclusions:
            excl_bits |= bit_of((e.variable, e.person)) if e.variable is not None else person_bits(e.person)
        if excl_bits:
            stage_reads = set().union(*(e for p, e in reads.items() if p[0] == "stage")) if reads else set()
            for sid in sids_of(stage_reads):
                add(sid, excl_bits)
    return k



def _resolve_dependencies(
    keys: list[tuple[str, str]],
    deps_of: dict[tuple[str, str], frozenset[str]],
    over: dict[tuple[str, str], int],
    affected: dict[str, int],
    runs: dict[tuple[tuple[str, str], ...], _Sim],
    new_runs: list[tuple[tuple[str, str], ...]],
    simulate: Any,
    slot_of: Mapping[str, Slot],
    order_ix: Mapping[str, int],
    default_label: Mapping[str, str],
    read_sid: Mapping[tuple[str, str], str],
    rounding_vars: Mapping[str, str],
    plan: Any,
    reg: Registry,
    index: _InputIndex,
    alive: tuple[str, ...],
    exact_deps: Any,
) -> None:
    """値ごとに、依存する分かれ目（deps_of）を計算の過程から決め、その候補の直積の全部の組を評価する（2026-11-12 の4回目。D21 R6）。

    依存する分かれ目の決め方（候補の組1つの評価ごと。attribution・masks_of）：
      1. 入力（変数, 人）・対象外・グループのインスタンスは、それを作った作り手（モジュールの build_inputs・グループの組み立て・段の関数）が
         読んだ1か所（判断・選択・注入の1か所、端数・読みの候補）に依存しうる。build_inputs とグループの組み立ては、読んだ分かれ目の
         直積が上限以内なら、直積の全部の組で呼んで出力ごとに依存する分かれ目を正確に決める（exact_deps。2つ以上の分かれ目が同時に
         変わるときだけ変わる出力も見落とさない）。超えたら安全側：build_inputs は人ごとに書くので、人 q の出力は関係する人
         （Slot.persons：DecisionSlot.persons の宣言か target から導いたもの）に q を含む分かれ目と人に結びつかない分かれ目に依存する
         とする（宣言の約束。下の 3 で確かめる）。段の関数の出力は人をまたぐので、段が読んだ全部の1か所に依存するとする。
         端数の候補を渡す入力変数はその端数の分かれ目に依存する。
      2. 値は、トレースで推移的に依存した入力（_Raw.inputs：段の値の由来を通したものと、人をまたぐ依存のつながった人を含む）と、
         集め忘れの検出が見る値の入力（_Raw.extra）が依存する分かれ目に依存する。計算の後の検出が対象外にしうる変数（検出の
         モジュールの変数の全部と、どこかの評価で検出が対象外にした変数）は、その検出が読んだ値の入力が依存する分かれ目にも依存する
         （target_bits。対象外を出さなかった組でも、ほかの組で出すかもしれない）。
      3. 確かめ：評価した2つの組で、1つの分かれ目だけが違うのに入力・対象外・グループが変わったら、その入力をその分かれ目に結びつける
         （affected。1 の宣言の約束が破れていても、評価した組の中では見落とさない）。
    読む1か所が値で変わる（ある分かれ目の候補でだけ別の1か所を読む）ことがあるので、依存する分かれ目の直積の全部の組を評価し、その
    どれかで依存する分かれ目が増えたら、増やして評価し直す（増えなくなるまで）。増えなくなった集まり D では、D の外の分かれ目を
    どう変えても、作り手は D の外の1か所を読まず（読んだ順に同じ値を返すので同じ道を通る）、値の入力は変わらない（1 の約束のもと）。
    依存する分かれ目だけで組合せが上限（MAX_ASSIGNMENTS）を超えた値は over に入れ、それ以上評価しない。
    """
    limit = MAX_ASSIGNMENTS
    bits = _Bits(index)
    bit_of, person_bits = bits.of, bits.person
    state = {"version": 0}
    targets: set[tuple[int, str | None, str]] = set()
    pairs_done: set[tuple[Any, Any]] = set()

    def attribution(run: _Sim) -> dict[str, int]:
        """分かれ目 → その分かれ目に依存する入力・グループ・対象外（ビット）。候補の組ごとに1回（読んだ1か所で決まる）。
        ワーカーで計算した組は、ワーカーが求めて親の番号に付け替えたもの（parallel）。"""
        hit = run.__dict__.get("_attribution")
        if hit is not None:
            return hit
        k = _attribution(run, exact_deps, bits, alive, rounding_vars, plan, read_sid, order_ix)
        run.__dict__["_attribution"] = k
        return k

    check_module = [m.name for m in reg.modules for _ in m.checks]  # 検出の番号 → モジュール（_assemble と同じ並び）
    candidates_of = _check_target_candidates(reg)
    module_vars: dict[str, list[str]] = {}
    for var, mod in sorted(reg.variable_module.items()):
        module_vars.setdefault(mod, []).append(var)
    tb_cache: dict[tuple[int, str], tuple[int, int]] = {}

    def target_bits(ci: int, q: str) -> int:
        """検出 ci が人 q について対象外にしうるもの（ビット）：検出のコードに書いた変数の名前（_check_target_candidates）と、どこかの
        評価で検出が対象外にした変数（人の対象外ならその人の全部）。対象外にした変数がコードに書いた名前になかったら（名前を組み立てる
        検出）、検出のモジュールの変数の全部にする。検出が対象外を出すかは検出が読んだ値で決まるので、これらに依存する値は、検出が
        読んだ値の入力が依存する分かれ目に依存する（その組で対象外を出さなくても、ほかの組で出すかもしれない）。"""
        hit = tb_cache.get((ci, q))
        if hit is not None and hit[0] == state["version"]:
            return hit[1]
        names = set(candidates_of[ci])
        seen = {var for c2, var, _p in targets if c2 == ci}
        if any(var is not None and var not in names for var in seen):
            names |= set(module_vars.get(check_module[ci], ())) | {var for var in seen if var is not None}
        b = 0
        for var in sorted(names):
            b |= bit_of((var, q))
        if None in seen:
            b |= person_bits(q)
        tb_cache[(ci, q)] = (state["version"], b)
        return b

    def masks_of(run: _Sim) -> dict[str, int]:
        hit = run.__dict__.get("_masks")
        if hit is not None and hit[0] == state["version"]:
            return hit[1]
        k = dict(attribution(run))
        for sid, b in affected.items():
            k[sid] = k.get(sid, 0) | b
        if run.check_bits:
            first = list(k.items())
            for (ci, q), cb in sorted(run.check_bits.items()):
                if not cb:
                    continue
                tb = target_bits(ci, q)
                for sid, m in first:
                    if m & cb:
                        k[sid] = k.get(sid, 0) | tb
        run.__dict__["_masks"] = (state["version"], k)
        return k

    def deps_in(run: _Sim, key: tuple[str, str]) -> frozenset[str]:
        cache = run.__dict__.setdefault("_deps", {})
        hit = cache.get(key)
        if hit is not None and hit[0] == state["version"]:
            return hit[1]
        raw = run.raws[key]  # type: ignore[index]
        b = raw.inputs | raw.extra
        res = frozenset(sid for sid, m in masks_of(run).items() if m & b)
        cache[key] = (state["version"], res)
        return res

    def labels(c: tuple[tuple[str, str], ...]) -> dict[str, str]:
        d = dict(default_label)
        d.update(c)
        return d

    def guard(new: list[tuple[tuple[str, str], ...]]) -> bool:
        """評価した組のうち1つの分かれ目だけが違う2つの組で変わった入力を、その分かれ目に結びつける（affected）。"""
        changed = False
        for c in new:
            lab = labels(c)
            for s in slot_of.values():
                if len(s.candidates) < 2:
                    continue
                for cand in s.candidates:
                    if cand.label == lab[s.id]:
                        continue
                    other = dict(lab)
                    other[s.id] = cand.label
                    c2 = tuple(sorted((sid, x) for sid, x in other.items() if x != default_label[sid]))
                    if c2 not in runs:
                        continue
                    pk = (c, c2) if c <= c2 else (c2, c)
                    if pk in pairs_done:
                        continue
                    pairs_done.add(pk)
                    b = _diff_bits(runs[c].build, runs[c2].build, index, person_bits)
                    if b & ~affected.get(s.id, 0):
                        affected[s.id] = affected.get(s.id, 0) | b
                        changed = True
        return changed

    todo = set(keys)
    while True:
        if new_runs:
            batch = list(new_runs)
            new_runs.clear()
            changed = guard(batch)
            for c in batch:
                found = runs[c].check_targets - targets
                if found:
                    targets.update(found)
                    changed = True
            if changed:
                state["version"] += 1
                todo = set(k for k in keys if k not in over)
        need: dict[tuple[tuple[str, str], ...], tuple[dict[str, Candidate], set[str]]] = {}
        later: set[tuple[str, str]] = set()
        for key in sorted(todo):
            d = deps_of[key]
            while True:
                slots_k = sorted((slot_of[sid] for sid in d), key=lambda s: order_ix[s.id])
                count = 1
                for s in slots_k:
                    count *= len(s.candidates)
                if count > limit:
                    over[key] = count
                    break
                grown = set(d)
                missing = False
                for a in assignments(slots_k, limit):
                    c = tuple(sorted((sid, x.label) for sid, x in a.items() if x.label != default_label[sid]))
                    run = runs.get(c)
                    if run is None or key not in run.raws:  # type: ignore[operator]
                        need.setdefault(c, (a, set()))[1].add(key[0])  # その組で集める値（基準でない組は要る値だけ集める）
                        missing = True
                        continue
                    grown |= deps_in(run, key)
                if missing:
                    d = frozenset(grown)
                    later.add(key)
                    break
                if grown == d:
                    break
                d = frozenset(grown)
            deps_of[key] = d
        if not need and not later and not new_runs:
            break
        # 求める組は互いに独立に計算できる（並べた順で runs・new_runs に入る。並列なら parallel がワーカーで計算する）
        simulate([(need[c][0], frozenset(need[c][1])) for c in sorted(need)])
        todo = later


# ---------------------------------------------------------------------------
# 候補の組のプロセスの並列（parallel.py。2026-11-12 の5回目）
# ---------------------------------------------------------------------------


def without_execution_options(query: Any) -> Any:
    """問いから、結果を変えない実行の指定（workers）を除いたもの（入力の SHA-256 に使う）。"""
    if isinstance(query, Mapping) and "workers" in query:
        return {k: v for k, v in query.items() if k != "workers"}
    return query


class _UnitHandle:
    """ワーカーの、評価の単位1つ（_evaluate_unit(handle=True) が返す）。候補の組を計算し、親が使う部分を返す（_pack）。"""

    def __init__(
        self, staged: Any, compute_base: Any, track: list[bool], slot_of: Mapping[str, Slot], index: _InputIndex,
        alive: tuple[str, ...], rounding_vars: Mapping[str, str], plan: Any, read_sid: Mapping[tuple[str, str], str],
        order_ix: Mapping[str, int], exact_deps: Any, exact_cache: dict[Any, list[Any]],
    ) -> None:
        self.staged = staged
        self.compute_base = compute_base
        self.track = track
        self.cands = {sid: {c.label: c for c in s.candidates} for sid, s in slot_of.items()}
        self.index = index
        self.bits = _Bits(index)
        self.args = (alive, rounding_vars, plan, read_sid, order_ix)
        self.exact_deps = exact_deps
        self.exact_cache = exact_cache
        self.base_sim: _Sim | None = None
        self.packed_base: tuple[dict[str, Any], bool, dict[Any, list[Any]]] | None = None
        self.installed = False

    def base(self, want: bool) -> tuple[dict[str, Any], bool, dict[Any, list[Any]]] | None:
        """基準の組を計算する（1回だけ。使い回しの表を温める）。want なら、その分かれ目の依存（入力の依存を集めるときだけ。親の
        _resolve_dependencies と同じ）と、作り手の依存の表（ほかのワーカーに渡す：install）も返す。"""
        if self.base_sim is None:
            self.base_sim = self.compute_base()
        if not want:
            return None
        if self.packed_base is None:
            sim = self.base_sim
            att = _attribution(sim, self.exact_deps, self.bits, *self.args) if self.track[0] else None
            self.packed_base = (_pack(sim, att), self.track[0], {k: list(v) for k, v in self.exact_cache.items()})
        return self.packed_base

    def install(self, exact: Mapping[Any, list[Any]] | None) -> None:
        """基準の組を計算したワーカーの、作り手の依存の表を足す（段の値の中身で引くので、ほかのワーカーの表も当たる。1回だけ）。"""
        if self.installed or not exact:
            return
        self.installed = True
        for key, entries in exact.items():
            self.exact_cache.setdefault(key, []).extend(entries)

    def run(self, labels: tuple[tuple[str, str], ...], needed: frozenset[str] | None, track: bool) -> dict[str, Any]:
        self.track[0] = track  # 入力の依存を集めるか（親の評価の今の値）
        a = {sid: self.cands[sid][label] for sid, label in labels}
        sim = self.staged(a, needed)
        return _pack(sim, _attribution(sim, self.exact_deps, self.bits, *self.args))


def _pack(sim: _Sim, attribution: dict[str, int]) -> dict[str, Any]:
    """ワーカーで計算した組のうち、親が使う部分（値の集め方の結果・検出・分かれ目の依存と、組どうしの入力の違い〔_diff_bits〕を
    求めるための最後の situation の入力の値・対象外・グループ）。由来と段の値は値（_Raw）に入っているので送らない。"""
    b = sim.build
    made: dict[int, InputValue] = {}

    def light(part: Mapping[tuple[str, str], InputValue]) -> dict[tuple[str, str], InputValue]:
        out: dict[tuple[str, str], InputValue] = {}
        for k, iv in part.items():
            x = made.get(id(iv))
            if x is None:
                x = made[id(iv)] = InputValue(iv.value)
            out[k] = x
        return out

    slim = YearBuild(
        {},
        b.persons,
        light(b.inputs),
        b.exclusions,
        {g: tuple(GroupInstance(i.id, dict(i.roles)) for i in insts) for g, insts in b.groups.items()},
    )
    parts = b.__dict__.get("_input_parts")
    if parts is not None:  # 入力の部分の形（_diff_bits が部分ごとに比べる：直列と同じ比べ方）
        slim.__dict__["_input_parts"] = (tuple(light(p) for p in parts[0]), light(parts[1]))
    return {
        "build": slim,
        "raws": sim.raws,
        "check_bits": sim.check_bits,
        "check_targets": sim.check_targets,
        "read_rounding": sim.read_rounding,
        "assembled": sim.__dict__["assembled"],
        "attribution": attribution,
    }


def _unpack(p: Mapping[str, Any]) -> _Sim:
    """ワーカーの結果（入力のビットは親の番号に付け替えたもの：parallel.Dispatcher）を、親の runs に入れる _Sim にする。"""
    sim = _Sim(p["build"], None, {}, p["read_rounding"], raws=p["raws"], check_bits=p["check_bits"], check_targets=p["check_targets"])
    sim.__dict__["assembled"] = p["assembled"]
    if p["attribution"] is not None:
        sim.__dict__["_attribution"] = p["attribution"]
    return sim


#: 親で候補の組を計算するとき（直列の単位・ワーカーが落ちたとき）のロック。単位をスレッドで並べて評価するので、プロセスの状態
#: （registry.CAPTURE・OpenFisca の Simulation の使い回し）を使う計算を重ねない
_COMPUTE = threading.RLock()


def _worker_handle(ir: Any, query: Any, injected: Any, scenario_index: int, job_index: int, system: OkuraTaxBenefitSystem) -> _UnitHandle:
    """ワーカーで、親と同じ手順で評価の単位を組み立て直す（evaluate・_evaluate_scenario と同じ材料と並び）。"""
    reg = system.registry
    q, qp = parse_query(query, path="$.query")
    inj, ip = parse_injected(injected, path="$.injected")
    if q is None or inj is None or qp or ip:
        raise AssertionError("ワーカーが問い・注入データを読めない（親で検査済みのはず）")
    sc = q.all_scenarios()[scenario_index]
    ir_s, sp = apply_scenario(ir, sc, scenario_index - 1)
    if sp:
        raise AssertionError("ワーカーがシナリオを当てられない（親で検査済みのはず）")
    scope = input_scope(ir_s, inj.entries, reg)
    units, _items = _plan(q, reg)
    _unit, evaluated_unit, forms_specs, views = _unit_jobs(units, q, reg)[job_index]
    h = _evaluate_unit(
        ir_s, evaluated_unit, system, reg, scope, q.filing_date, inj, forms_specs, _Engine(system), views=views, handle=True
    )
    if not isinstance(h, _UnitHandle):
        raise AssertionError("ワーカーの単位に値がない（親は値のない単位を割り振らない）")
    return h


def _round_targets_final(sim: _Sim, reg: Registry, year: int, extra: Iterable[OutputSpec]) -> list[OutputSpec]:
    """最後の計算で late_reads の値を集めるときの値：計算した出力（依存の順）と、late_reads の変数のうち出力でないもの。"""
    key = f"year:{year}-01-01:1"
    graph = sim.graph()
    outputs = {s.variable for s in reg.outputs}
    return [s for s in reg.outputs if (s.variable, key) in graph] + [s for s in extra if s.variable not in outputs]


def _round_targets(plan: Any, r: int, sim: _Sim, reg: Registry, year: int) -> list[OutputSpec]:
    """中間の回で組み立てる値：その回で計算した出力（依存の順）と、読む変数のうち出力でないもの。"""
    key = f"year:{year}-01-01:1"
    graph = sim.graph()
    targets = [s for s in reg.outputs if (s.variable, key) in graph]
    return targets + list(plan.read_specs[r])


def _exclusion_map(build: YearBuild) -> dict[tuple[str | None, str], frozenset[str]]:
    out: dict[tuple[str | None, str], set[str]] = {}
    for e in build.exclusions:
        out.setdefault((e.variable, e.person), set()).add(e.reason.reason)
    return {k: frozenset(v) for k, v in out.items()}


_GROUP_PLURAL: Mapping[str, str] = {e.key: e.plural for e in ENTITIES if not e.is_person}


def _group_uses(d: ConceptDictionary, concept_id: str) -> frozenset[str]:
    """値の概念が（宣言した依存をたどって）使うグループ（複数形）：グループの概念（所得税.扶養の割当て・所得税.法律婚など）への依存。"""
    cache = memo(d, "group_uses")
    hit = cache.get(concept_id)
    if hit is None:
        hit = cache[concept_id] = frozenset(_GROUP_PLURAL[c.entity] for c in d.closure(concept_id) if c.entity in _GROUP_PLURAL)
    return hit


def attached_groups(used: frozenset[str], cross: bool, all_groups: Iterable[str]) -> frozenset[str]:
    """値に由来（状態・事実・根拠・依存する入力）を付けるグループ（複数形）。2026-11-13（B1 の直し）。

    used は値の概念が宣言した依存をたどって使うグループ（_group_uses）。式がグループの組み方を使うなら宣言がある（構造の検査：
    check_group_uses・式の依存の宣言）ので、人をまたぐ値（cross）でも宣言したグループだけを通る。以前は、人をまたぐ値に全部のグループを
    付けていた（「どのグループを通ったかはトレースに残らない」ための安全側）。そのため、所得税の値（ひとり親・扶養親族など）が、
    住民税の扶養の割当て・健康保険・国保の世帯のグループの組み立て（ほかの制度の注入点・段の値）に依存したことになり、家族が複数の
    市町村に住むと所得税の値まで候補の組合せの上限を超えた（docs/measurements/20261113_family-run_findings.md の B1）。
    人をまたぐのに宣言したグループが1つもない値は、宣言の漏れなので、以前と同じ安全側（全部のグループ）にする。
    """
    if cross and not used:
        return frozenset(all_groups)
    return used


_PERIODS: dict[str, Any] = {}


def _period(period: str) -> Any:
    """年分の期間のオブジェクト（文字列の解析は年分ごとに1回。OpenFisca は文字列の期間を呼ぶたびに解析する）。"""
    p = _PERIODS.get(period)
    if p is None:
        p = _PERIODS[period] = periods.period(period)
    return p


def new_simulation(system: OkuraTaxBenefitSystem, build: YearBuild, period: Any) -> Any:
    """situation（YearBuild）から OpenFisca の Simulation を作る。

    SimulationBuilder.build_from_entities に値つきの situation を渡すと、値ごとに期間の文字列を解析する（家族1組で数万回）。
    ここでは人とグループだけを build_from_entities で組み立て、入力の値は変数ごとに配列にして Holder.set_input で入れる。
    値の変換（Variable.check_set_value と同じ dtype への変換、列挙の名前 → 番号）と、変数の終わりの日（Variable.end）の扱いは
    build_from_entities（finalize_variables_init）と同じ。入力は全部が年分の期間（build_year が書く形）。
    """
    situation = build.situation
    skeleton: dict[str, Any] = {k: v for k, v in situation.items() if k != "人物一覧"}
    skeleton["人物一覧"] = {p: {} for p in build.persons}
    sim = SimulationBuilder().build_from_entities(system, skeleton)
    _set_inputs(system, sim, build, period)
    return sim


def _set_inputs(system: OkuraTaxBenefitSystem, sim: Any, build: YearBuild, period: Any, *, clear_skipped: bool = False) -> None:
    """build.inputs の値を、変数ごとの配列にして Holder.set_input で入れる（入力のない人は変数の既定値）。

    clear_skipped：終わりの日（Variable.end）の後で書かない変数の、前に書いた値を消す（使い回す Simulation の入れ直し）。
    """
    index = {p: i for i, p in enumerate(build.persons)}
    by_var: dict[str, list[tuple[int, Any]]] = {}
    for (var, pid), iv in build.inputs.items():
        by_var.setdefault(var, []).append((index[pid], iv.value))
    n = len(build.persons)
    population = sim.persons
    start = period.start.date
    for var in sorted(by_var):
        variable = system.variables[var]
        if variable.end is not None and start > variable.end:
            if clear_skipped:
                population.get_holder(var).delete_arrays()
            continue
        items = by_var[var]
        array = variable.default_array(n)
        if variable.value_type is Enum:
            for i, v in items:
                array[i] = variable.check_set_value(v)
        else:
            idx = numpy.fromiter((i for i, _ in items), dtype=numpy.int64, count=len(items))
            array[idx] = numpy.array([v for _, v in items], dtype=variable.dtype)
        population.get_holder(var).set_input(period, array)


def _simulate(
    build: YearBuild,
    system: OkuraTaxBenefitSystem,
    reg: Registry,
    period: str,
    rounding_vars: Mapping[str, str],
    variables: Iterable[str],
    engine: _Engine | None = None,
) -> _Sim:
    """候補の組1つの1回の計算（トレースつき）。variables を計算する。式が引いた端数の候補の入力変数の分かれ目の ID も返す。

    engine を渡すと、前の回の Simulation を使い回す（_Engine。値とトレースの依存は新しい Simulation と同じ）。
    """
    p = _period(period)
    if engine is not None:
        sim = engine.prepare(build, p)
    else:
        sim = new_simulation(system, build, p)
        sim.trace = True
    cache: dict[str, Any] = {}
    for var in variables:
        if var not in cache:
            cache[var] = sim.calculate(var, p)
    for var in _collected_implemented(reg):  # 集め忘れの検出が見る値（トレースに残す）
        if var not in cache:
            cache[var] = sim.calculate(var, p)
    out = _Sim(build, sim, cache, frozenset(), engine=engine)
    if rounding_vars:
        out.read_rounding = frozenset(rounding_vars[k[0]] for k in out.graph() if k[0] in rounding_vars)
    return out


def _assemble(
    run: _Run,
    ir: Mapping[str, Any],
    year: int,
    system: OkuraTaxBenefitSystem,
    reg: Registry,
    incomplete: Mapping[str, tuple[str, ...]],
    xp: frozenset[tuple[str, str]] = frozenset(),
    *,
    track_inputs: bool = True,
    targets: Iterable[OutputSpec] | None = None,
    pending: frozenset[str] = frozenset(),
    persons: frozenset[str] | None = None,
    filing_date: FilingDate | None = None,
    value_id: Any = None,
    needed_from: Iterable[str] | None = None,
    zero_index: Mapping[tuple[str, str], list[str]] | None = None,
    requested: set[str] | None = None,
    index: _InputIndex | None = None,
    check_deps: bool = False,
    reuse: dict[str, Any] | None = None,
) -> None:
    """候補の組1つの計算の結果から、出力の変数 × 人 の値・状態・根拠・対象外を集める。track_inputs は分かれ目があるときだけ（時間を抑える）。

    reuse（評価の単位で共有する表。2026-11-12 の4回目）：前の回・前の候補の組で集めた値（_Raw）を、その値が推移的に依存した入力
    （_Raw.inputs と extra）が、前の situation と今の situation で同じオブジェクト・同じ対象外・同じグループのインスタンスなら
    使い回す（値も由来も入力の関数なので同じになる）。比べるのは situation の組ごとに1回作る「変わった入力のビット」との AND だけ
    （_AsmSig・_changed_mask）。トレースを止める出力の集まりが同じ集め方の間だけ（閉包の形が同じ）。

    check_deps（値ごとの候補の評価の最後の計算。2026-11-12 の4回目）：計算の後の検出ごと・人ごとに、検出が読んだ値の入力（ビット）と、
    検出が出した対象外を run.check_bits・run.check_targets に入れる（検出が対象外にする値が、検出の読んだ値の分かれ目に依存するとみなすため）。
    集め忘れの検出（_coverage）が見る値の入力は、集約点の値の _Raw.extra に入れる（同じく依存する分かれ目を決めるため）。

    _Raw.inputs は index（評価の単位で共有する入力の番号。省略は run.index か新しい番号）のビットで持つ（run.index に入れる）。

    targets は集める変数（省略は全部の出力。依存の順）。トレースは targets の変数で止める（targets でない出力は途中の変数としてたどる）。
    pending は段階評価の中間の回で、まだ計算していない段の出力に依存する変数（計算の後の検出が読んだらその検出を飛ばす）。
    persons は集める人（省略は全員。人のつながりの評価ではそのつながりの人だけ）。value_id は（概念 ID, 人）→ 値の ID（省略は所得税の年分の ID）。
    注入されていない（候補を持たない）注入点の分かれ目（InputValue.missing）は、状態と同じ道で依存する値へ伝える。
    requested を渡すと、集めた値に使った変数（値・検出・集め忘れの検出・根拠が引いたもの。飛ばした検出の分は除く）を足す。
    """
    assert run.sim is not None
    ix = index if index is not None else (run.index if run.index is not None else _InputIndex())
    run.index = ix
    bit_of = ix.of
    targets = list(targets) if targets is not None else None
    vid = value_id if value_id is not None else (lambda c, p: _value_id(year, p, c))
    build = run.build
    sim = run.sim.sim
    period = _period(str(year))
    order = list(sim.persons.ids)
    if order != list(build.persons):
        raise AssertionError("situation の人の並びと OpenFisca の人の並びが違う")
    cache = run.sim.cache

    sink: list[set[str] | None] = [requested]

    def calc(var: str) -> Any:
        if sink[0] is not None:
            sink[0].add(var)
        if var not in cache:
            cache[var] = sim.calculate(var, period)
        return cache[var]

    def guarded(var: str) -> Any:
        if var in pending:
            raise _PendingStage(var)
        return calc(var)

    instant = f"{year}-01-01"
    params_at = system.get_parameters_at_instant(instant)
    check_ctx = CheckContext(year, tuple(order), guarded if pending else calc, params_at, ir, filing_date)
    check_excl: list[Exclusion] = []
    check_reads: list[tuple[int, frozenset[str]]] = []  # check_deps：検出の番号 → 検出が引いた値
    check_src: list[tuple[int, Exclusion]] = []
    for ci, chk in enumerate(c for m in reg.modules for c in m.checks):
        if requested is not None or check_deps:
            sink[0] = set()  # 飛ばした検出が引いた値は、結果に使わない
        try:
            found = list(chk(check_ctx))
            check_excl += found
            check_src += [(ci, e) for e in found]
        except _PendingStage:
            continue  # 中間の回：まだ決まっていない段の出力に依存する値を読む検出は、その回では意味がない
        finally:
            got, sink[0] = sink[0], requested
        if requested is not None and got is not None:
            requested |= got
        if check_deps:
            check_reads.append((ci, frozenset(got or ())))
    graph = run.sim.graph()
    all_outputs = {s.variable for s in reg.outputs}
    # トレースを止める変数：集める出力（targets のうち出力のもの。段の読む途中の変数〔read_specs〕では止めない）
    outputs = all_outputs if targets is None else {s.variable for s in targets if s.variable in all_outputs}
    person_excl: dict[str, list[OutOfScopeReason]] = {}
    input_excl: dict[tuple[str, str], list[OutOfScopeReason]] = {}
    for e in list(build.exclusions) + check_excl:
        if e.variable is None:
            person_excl.setdefault(e.person, []).append(e.reason)
        else:
            input_excl.setdefault((e.variable, e.person), []).append(e.reason)
    if zero_index is None:
        zero_index = _zero_index(reg, ir, year)
    zero_cache: dict[tuple[str, str], tuple[bool, tuple[str, ...]]] = {}

    def zero(concept: Concept, pid: str) -> tuple[bool, tuple[str, ...]]:
        k = (concept.id, pid)
        if k not in zero_cache:
            zero_cache[k] = _zero_blockers(concept, pid, zero_index)
        return zero_cache[k]

    comp = _components(build.groups, order)
    comp_members: dict[int, list[str]] = {}
    for q in order:
        comp_members.setdefault(comp[q], []).append(q)
    # グループ × 人 → その人が入るインスタンス（人ごとに全部のインスタンスを走査しない）
    insts_of: dict[tuple[str, str], list[Any]] = {}
    for g, insts in build.groups.items():
        for inst in insts:
            for member in {p for ps in inst.roles.values() for p in ps}:
                insts_of.setdefault((g, member), []).append(inst)
    group_names = sorted(build.groups)

    def persons_of(cl: _Closure, pid: str) -> list[str]:
        # 人をまたぐ依存：同じグループでつながった人の全部（安全側。どのグループを通ったかはトレースに残らない）
        return comp_members[comp[pid]] if cl.cross else [pid]

    def unknown(var: str, pid: str, cl: _Closure) -> list[OutOfScopeReason]:
        """var の pid の値を決められない理由（人・入力・途中の変数の対象外、0とみなせない仮置きの変数、ほかの年分の値）。"""
        out: list[OutOfScopeReason] = list(person_excl.get(pid, ()))
        # 値の変数そのもの（var）は、その人の対象外だけを見る。OpenFisca では同じ変数・同じ期間を式の中で引けない（循環）ので、
        # ほかの人の var の対象外はこの値に依存しない（2026-11-11 の結合のレビュー：国外居住親族自身の所得控除の額の対象外が、
        # 扶養所属のグループを通して申告者の同じ名前の控除の額へ伝わっていた）。トレースでたどった変数は、つながった人の全部を見る（安全側）
        out += input_excl.get((var, pid), [])
        key = (id(cl), var)
        ivs = sorted_vars.get(key)
        if ivs is None:
            # 理由を出しうる変数（だれかの対象外の入力か、仮置きの入力）だけを、同じ順で（cl を持っておく：id を使い回されないように）
            ivs = sorted_vars[key] = (
                cl,
                [iv for iv in sorted(cl.variables - {var}) if iv in excl_vars or (iv in cl.inputs and system.is_placeholder(iv))],
            )
        scope = persons_of(cl, pid)
        for iv in ivs[1]:
            for q in cl.readers(iv, pid, scope):  # 本人についてだけ読む変数は、本人の対象外だけを見る（_Closure.crossed）
                out += input_excl.get((iv, q), [])
                if iv in cl.inputs and system.is_placeholder(iv):
                    ok, ids = zero(reg.placeholders[iv], q)
                    if not ok:
                        out.append(_placeholder_reason(reg.placeholders[iv], ids))
        if cl.other_years:
            out.append(
                OutOfScopeReason(
                    OutOfScopeCategory.NOT_IMPLEMENTED,
                    "式がほかの年分の値（" + "・".join(sorted(cl.other_years)) + "）を引く。situation は年分ごとに作り、"
                    "ほかの年分の値を入れていない（OpenFisca は既定値を返す）ので評価しない",
                )
            )
        return out

    closures: dict[str, _Closure] = {}
    sorted_vars: dict[tuple[int, str], tuple[_Closure, list[str]]] = {}
    excl_vars = {v for v, _ in input_excl}  # 値ごとに並べ直さない（人の数だけ同じ並べ替えをしていた）
    param_basis: dict[str, list[BasisEntry]] = {}

    # 使い回す Simulation のトレースの閉包（_SimState.closures）：同じ項目のオブジェクトなら、その下の依存は変わっていない
    engine_state = run.sim.engine.current if run.sim.engine is not None else None
    ccache = engine_state.closures if engine_state is not None and engine_state.sim is sim else None
    stop_key = frozenset(outputs)
    period_k = f"year:{year}-01-01:1"
    if ccache is not None and outputs is not all_outputs and all(
        v in outputs for v in all_outputs if (v, period_k) in graph
    ):
        # 止める出力が「この回のトレースにある出力の全部」を含む（段階評価の回・late_reads の値）：閉包がたどるのはトレースにある
        # 項目だけなので、全部の出力で止めたのと同じ閉包になる。同じキーにして、回をまたいで閉包を使い回す（2026-11-12）
        outputs = all_outputs
    if outputs is all_outputs:
        stop_key = _ALL_OUTPUTS

    def closure_of(var: str, stop: set[str], skey: frozenset[str]) -> _Closure:
        if ccache is None:
            return _closure(graph, var, year, system, stop, xp)
        top = graph.get((var, period_k))
        if top is None:
            return _closure(graph, var, year, system, stop, xp)
        ck = (var, skey)
        hit = ccache.get(ck)
        if hit is not None and hit[0] is top:
            return hit[1]
        cl = _closure(graph, var, year, system, stop, xp)
        ccache[ck] = (top, cl)
        return cl

    pcache = engine_state.pairs if ccache is not None else {}

    def var_pairs(cl: _Closure, pid: str, scope: list[str]) -> int:
        # 閉包の通った変数 × その変数を読みうる人（_Closure.readers）のビット（閉包と人の組ごとに1回だけ作る。閉包は使い回すので
        # 回をまたいで使える）
        k = (id(cl), pid, tuple(scope), id(ix))
        hit = pcache.get(k)
        if hit is None or hit[0] is not cl or hit[1] is not ix:
            b = 0
            for iv in cl.variables:
                for q in cl.readers(iv, pid, scope):
                    b |= bit_of((iv, q))
            hit = pcache[k] = (cl, ix, b)
        return hit[2]

    def unknown_any(var: str, pid: str) -> list[OutOfScopeReason]:
        if var not in closures:
            closures[var] = closure_of(var, set(), frozenset())
        return unknown(var, pid, closures[var])

    selected = list(targets) if targets is not None else list(reg.outputs)
    out_closures: dict[str, _Closure] = {}

    def out_closure(var: str) -> _Closure:
        if var not in out_closures:
            out_closures[var] = closure_of(var, outputs, stop_key)
        return out_closures[var]

    if needed_from is not None:
        # 段階評価の中間の回：段の読む値と、それが（出力の変数で止めたトレースで）依存した出力だけを集める（ほかは使わない）。
        # トレースを止める出力の集まり（outputs）は変えないので、集めた値は全部を集めたときと同じ
        need: set[str] = set()
        stack = list(needed_from)
        while stack:
            v = stack.pop()
            if v in need:
                continue
            need.add(v)
            stack.extend(out_closure(v).out_deps)
        selected = [s for s in selected if s.variable in need]
    coverage = _coverage(reg, calc, order, zero_index, unknown_any, selected, persons)
    from_set = ix.from_set
    vb_memo: dict[tuple[str, str], int] = {}

    def var_input_bits(var: str, q: str) -> int:
        """変数 var の人 q の値が推移的に依存した入力（ビット。集めた値なら _Raw.inputs と extra）。計算の後の検出・集め忘れの検出が
        読んだ値の入力を求めるのに使う（値ごとの候補の評価の、依存する分かれ目。2026-11-12 の4回目）。"""
        r = run.raws.get((var, q))
        if r is not None and isinstance(r.inputs, int):
            return r.inputs | r.extra
        k = (var, q)
        hit = vb_memo.get(k)
        if hit is not None:
            return hit
        vb_memo[k] = 0  # 循環の守り（トレースは循環しないが、念のため）
        cl = closure_of(var, outputs, stop_key)
        scope = persons_of(cl, q)
        b = bit_of(k) | var_pairs(cl, q, scope)
        for iv in sorted(cl.inputs):
            for p2 in cl.readers(iv, q, scope):
                prov = build.inputs.get((iv, p2))
                if prov is not None and prov.uses:
                    for u in prov.uses:
                        b |= from_set(u.inputs) | (from_set(u.extra) if u.extra else 0)
        # グループの組み立て：値の概念が宣言したグループだけ（attached_groups。2026-11-13：以前は人をまたぐ値に全部のグループ）
        concept = reg.dictionary.by_variable(var)
        used = _group_uses(reg.dictionary, concept.id) if concept is not None else frozenset()
        for g in sorted(attached_groups(used, cl.cross, group_names)):
            for p2 in scope:
                b |= bit_of((f"group:{g}", p2))
                for inst in insts_of.get((g, p2), ()):
                    for u in inst.uses or ():
                        b |= from_set(u.inputs) | (from_set(u.extra) if u.extra else 0)
        for dv in sorted(cl.out_deps):
            for p2 in cl.readers(dv, q, scope):
                b |= var_input_bits(dv, p2)
        vb_memo[k] = b
        return b

    agg_cache: dict[int, Any] = reuse.setdefault("uses_aggregate", {}) if reuse is not None else {}

    def uses_aggregate(uses: Any) -> tuple[Any, ...]:
        """段の値の組（uses）の由来をまとめたもの（状態・対象外の理由・依存の値の ID・根拠・事実・入力のビット・extra・注入の分かれ目）。"""
        hit = agg_cache.get(id(uses))
        if hit is not None and hit[0] is uses:
            return hit[1]
        st: set[State] = set()
        rs: list[OutOfScopeReason] = []
        ds: set[str] = set()
        bs: list[BasisEntry] = []
        seen_b: set[int] = set()
        fs: set[str] = set()
        ib = 0
        eb = 0
        ms: dict[str, Split] = {}
        seen_u: set[int] = set()
        for u in uses:
            if id(u) in seen_u:
                continue
            seen_u.add(id(u))
            if u.missing:
                ms.update({m.id: m for m in u.missing})
            st |= u.states
            rs.extend(u.reasons)
            ds.update(u.value_ids)
            for b in u.basis:
                if id(b) not in seen_b:
                    seen_b.add(id(b))
                    bs.append(b)
            fs.update(u.facts)
            ib |= u.inputs if isinstance(u.inputs, int) else from_set(u.inputs)
            if u.extra:
                eb |= from_set(u.extra)
        agg = (frozenset(st), tuple(dict.fromkeys(rs)), frozenset(ds), tuple(bs), frozenset(fs), ib, eb, ms)
        agg_cache[id(uses)] = (uses, agg)  # uses を持っておく（id を使い回されないように）
        return agg

    use_reuse = reuse is not None and track_inputs and persons is None
    cur_sig = _AsmSig(build, frozenset(build.exclusions) | frozenset(check_excl)) if use_reuse else None
    # 閉包の形はトレースを止める出力の集まりで決まるので、その集まりごとに分ける
    entries: dict[str, list[Any]] = reuse.setdefault(("entries", stop_key), {}) if use_reuse else {}  # type: ignore[union-attr]
    for spec in selected:
        if use_reuse:
            hit = None
            for sig, raws_of, req in reversed(entries.get(spec.variable, ())):
                mask = _changed_mask(reuse, sig, cur_sig, ix)  # type: ignore[arg-type]
                if all(((r.inputs | r.extra) & mask) == 0 for r in raws_of.values()):
                    hit = (raws_of, req)
                    break
            if hit is not None:
                run.raws.update(hit[0])
                if requested is not None:
                    requested |= hit[1]
                continue
            spec_req: set[str] = set()
            if requested is not None:
                sink[0] = spec_req
        cl = out_closure(spec.variable)
        out_dep_ids = [(dv, reg.dictionary.by_variable(dv).id) for dv in sorted(cl.out_deps)]  # type: ignore[union-attr]
        own_input = not system.variables[spec.variable].formulas
        raw_values = calc(spec.variable)
        groups_attached = attached_groups(_group_uses(reg.dictionary, spec.concept), cl.cross, group_names)
        # 人ごとに同じ（作り直さない）。名前の順にたどる（集合の順はプロセスごとに変わり、対象外の理由の文の並びが実行ごとに変わっていた：
        # 2026-11-12 の4回目に直した決定性の不具合）
        direct_of = tuple(sorted(set(cl.inputs) | ({spec.variable} if own_input else set())))
        covered_vars = _coverage_variables(reg, spec) if track_inputs else ()
        for idx, pid in enumerate(order):
            if persons is not None and pid not in persons:
                continue
            scope_persons = persons_of(cl, pid)
            states: set[State] = set()
            facts: set[str] = set()
            reasons: list[OutOfScopeReason] = unknown(spec.variable, pid, cl)
            inputs: int = bit_of((spec.variable, pid)) if track_inputs else 0  # 入力の集まり（ix のビット）
            extra: int = 0
            direct = direct_of
            deps: set[str] = set()
            stage_basis: list[BasisEntry] = []
            missing: dict[str, Split] = {}

            seen_basis: set[int] = set()
            seen_entries: set[int] = set()  # 段の値の根拠の項目（同じオブジェクトは1回）
            seen_tuples: dict[int, bool] = {}  # 伝えた uses の組（同じオブジェクト）→ own で伝えたか

            def absorb(uses: Any, basis: Iterable[BasisEntry], *, own: bool) -> None:
                # 段階の間で引いた値の由来（前の段の値の状態・対象外・根拠・依存）を、この値へ伝える。
                # 同じ由来（同じオブジェクト）を2回目に伝えても何も変わらない（集合の和。理由・根拠の並びは最初の出現の順のまま）ので飛ばす。
                # uses の組は段の出力どうしで同じオブジェクトなので、組ごとに1回まとめたもの（uses_aggregate）を足す（2026-11-12 の4回目）
                nonlocal states, facts, deps, reasons, inputs, extra
                if id(basis) not in seen_basis:
                    seen_basis.add(id(basis))
                    stage_basis.extend(basis)
                if not uses:
                    return
                # 同じ uses の組を、前と同じか弱い own で伝え直しても何も変わらない（組の全部の値が、その own 以上で伝わっている）
                done = seen_tuples.get(id(uses))
                if done is not None and (done or not own):
                    return
                seen_tuples[id(uses)] = own or bool(done)
                agg = uses_aggregate(uses)
                if own:
                    facts |= agg[4]
                if done is not None:
                    return  # 前に own なしで伝えた組：事実の ID だけが増える
                states |= agg[0]
                if agg[1]:
                    reasons.extend(agg[1])  # reasons はこの値だけの新しいリスト（unknown が作る）
                deps |= agg[2]
                for b in agg[3]:
                    if id(b) not in seen_entries:
                        seen_entries.add(id(b))
                        stage_basis.append(b)
                if agg[7]:
                    missing.update(agg[7])
                if track_inputs:
                    inputs |= agg[5]
                    extra |= agg[6]

            for iv in direct:
                for q in cl.readers(iv, pid, scope_persons):  # 本人についてだけ読む入力は本人の分だけ（_Closure.crossed）
                    prov = build.inputs.get((iv, q))
                    if track_inputs:
                        inputs |= bit_of((iv, q))
                    if prov is not None:
                        states |= prov.states
                        if prov.missing:
                            missing.update({m.id: m for m in prov.missing})
                        if q == pid:
                            facts.update(prov.record_ids)
                        if prov.uses or id(prov.basis) not in seen_basis:
                            absorb(prov.uses, prov.basis, own=q == pid)
            if track_inputs:
                inputs |= var_pairs(cl, pid, scope_persons)
            # グループの組み立ての由来（婚姻の記録・扶養の所属の選択など）：値の概念が宣言したグループに付ける
            # （attached_groups。2026-11-13：以前は人をまたぐ値に全部のグループを付け、ほかの制度のグループの由来が伝わっていた）
            for g in group_names:
                if g not in groups_attached:
                    continue
                for inst in insts_of.get((g, pid), ()):
                    states |= inst.states
                    facts |= set(inst.record_ids)
                    absorb(inst.uses, inst.basis, own=True)
                    if track_inputs:
                        inputs |= bit_of((f"group:{g}", pid))
                if track_inputs and cl.cross:
                    # 人をまたぐ値は、つながった人の全部のグループの組み方に依存する（ほかの人のインスタンスが変わると、つながった人が変わる）
                    for q in scope_persons:
                        inputs |= bit_of((f"group:{g}", q))
            has_records = bool(facts)
            for dv, dep_id in out_dep_ids:
                for q in cl.readers(dv, pid, scope_persons):  # 本人についてだけ読む出力は本人の値だけ（_Closure.crossed）
                    d = run.raws[(dv, q)]
                    deps.add(vid(dep_id, q))
                    states |= d.states
                    if d.missing:
                        missing.update(d.missing)
                    if track_inputs:
                        inputs |= d.inputs
                        extra |= d.extra
                    if d.reasons:
                        reasons += d.reasons
                    if q == pid:
                        has_records = has_records or d.has_records
            if spec.needs_complete_income and pid in incomplete:
                reasons.append(
                    OutOfScopeReason(
                        OutOfScopeCategory.NOT_IMPLEMENTED,
                        "この人に、どの規則モジュールも使わない所得に関係しうる記録・判断・選択がある（全部の所得に依存する値は出さない）",
                        incomplete[pid],
                    )
                )
            reasons += coverage.get((spec.variable, pid), [])
            for cv in covered_vars:  # 集め忘れの検出が見る値（その値で対象外になるかが決まる）の入力
                extra |= var_input_bits(cv, pid)
            basis: list[BasisEntry] = []
            value: Any = None
            if not reasons:
                value = _to_python(raw_values[idx], spec.value_type)
                basis = list(reg.rules_for(spec.variable, year))
                builder = reg.basis_builders.get(spec.variable)
                if builder is not None:
                    basis += builder(
                        BasisContext(year, instant, system.parameters, params_at, calc, idx, pid, filing_date)
                    )
                else:
                    if spec.variable not in param_basis:  # 同じ変数の値は同じトレース（cl）なので、人ごとに作り直さない
                        param_basis[spec.variable] = [parameter_basis(system.parameters, n, inst) for n, inst in sorted(cl.params)]
                    basis += param_basis[spec.variable]
                basis += stage_basis
            run.raws[(spec.variable, pid)] = _Raw(
                value=value,
                states=states,
                facts=facts,
                deps=deps,
                reasons=list(dict.fromkeys(reasons)),  # 同じ理由は1回（依存をたどるたびに重なる。まとめた結果は変わらない）
                basis=basis,
                has_records=has_records,
                inputs=inputs,
                missing=missing,
                extra=extra & ~inputs,
            )
        if use_reuse:
            if requested is not None:
                requested |= spec_req
                sink[0] = requested
            lst = entries.setdefault(spec.variable, [])
            lst.append((cur_sig, {(spec.variable, p): run.raws[(spec.variable, p)] for p in order}, frozenset(spec_req)))
            if len(lst) > 4:
                del lst[0]
    if check_deps:
        bits: dict[tuple[int, str], int] = {}
        for ci, names in check_reads:
            for pid in order:
                if persons is not None and pid not in persons:
                    continue
                b = 0
                for name in sorted(names):
                    b |= var_input_bits(name, pid)
                bits[(ci, pid)] = b
        run.check_bits = bits
        run.check_targets = frozenset((ci, e.variable, e.person) for ci, e in check_src)


def _coverage_variables(reg: Registry, spec: OutputSpec) -> tuple[str, ...]:
    """集め忘れの検出（_coverage）が spec の値について値を見る、実装済みの概念の変数（登録ごとに1回だけ求める）。"""
    cache = memo(reg, "coverage_variables")
    hit = cache.get(spec.variable)
    if hit is None:
        d = reg.dictionary
        c = d.concept(spec.concept)
        out: list[str] = []
        if c.aggregates is not None:
            covered = set(c.declared_targets())
            for k in d.concepts:
                if c.id not in k.collected_by or not k.variables:
                    continue
                if k.id in covered and (k.implemented or k.variables[0] not in reg.placeholders):
                    continue
                if k.implemented:
                    out.append(k.variables[0])
        hit = cache[spec.variable] = tuple(out)
    return hit


def _collected_implemented(reg: Registry) -> tuple[str, ...]:
    """「集める先」を持つ実装済みの概念の変数（集め忘れの検出が値を見る）。登録ごとに1回だけ求める。"""
    cache = memo(reg, "collected_implemented")
    if "vars" not in cache:
        cache["vars"] = tuple(
            k.variables[0]
            for k in reg.dictionary.concepts
            if k.collected_by and k.implemented and k.variables and k.variables[0] in reg.variable_module
        )
    return cache["vars"]


def _coverage(
    reg: Registry,
    calc: Any,
    order: list[str],
    zero_index: Mapping[tuple[str, str], list[str]],
    unknown: Any = None,
    targets: Iterable[OutputSpec] | None = None,
    persons: frozenset[str] | None = None,
) -> dict[tuple[str, str], list[OutOfScopeReason]]:
    """集約点の集め忘れの検出：集約点がまだ引いていない「集める先」の概念が、その人で0と言えなければ対象外。

    実装済みの概念は、値が0でないか、値そのものが決まらない（unknown(変数, 人) が理由を返す：入力の対象外・0とみなせない
    仮置きの変数など。対象外の入力は0を入れて計算するので、値が0でも0と言えない）とき。
    """
    out: dict[tuple[str, str], list[OutOfScopeReason]] = {}
    d = reg.dictionary
    for spec in targets if targets is not None else reg.outputs:
        c = d.concept(spec.concept)
        if c.aggregates is None:
            continue
        covered = set(c.declared_targets())
        for k in d.concepts:
            if c.id not in k.collected_by or not k.variables:
                continue
            if k.id in covered and (k.implemented or k.variables[0] not in reg.placeholders):
                continue
            var = k.variables[0]
            for idx, pid in enumerate(order):
                if persons is not None and pid not in persons:
                    continue
                if k.implemented:
                    v = calc(var)[idx]
                    why = unknown(var, pid) if unknown is not None else []
                    if int(v) == 0 and not why:
                        continue
                    ids: tuple[str, ...] = tuple(sorted({i for r in why for i in r.record_ids}))
                else:
                    ok, ids = _zero_blockers(k, pid, zero_index)
                    if ok:
                        continue
                out.setdefault((spec.variable, pid), []).append(
                    OutOfScopeReason(
                        OutOfScopeCategory.NOT_IMPLEMENTED,
                        f"集約点 {c.id} がまだ集めない {k.id}（担当 {k.module}）が、この人で0と言えない",
                        ids,
                    )
                )
    return out


def _merge_value(
    spec: OutputSpec,
    pid: str,
    plan: _ValuePlan,
    year: int,
    value_id: Any = None,
    time_of: Any = None,
    index: _InputIndex | None = None,
) -> ResultValue:
    """値1つの候補の組ごとの値をまとめて ResultValue にする（D21 R6・D22 S3）。

    plan.runs は、その値が依存する分かれ目（plan.slots）の候補の直積の全部の組の評価（上限を超えたら基準の組だけ）。
    value_id は（概念 ID, 人）→ 値の ID、time_of は概念 ID → 時点（省略は所得税の年分）。index は _Raw.inputs のビットの番号。
    注入されていない（候補を持たない）注入点に依存する値は未確定（分かれ目の決める手段は注入、候補ごとの値はなし：D19）。
    """
    vid = value_id if value_id is not None else (lambda c, p: _value_id(year, p, c))
    tof = time_of if time_of is not None else (lambda c: TimeKey("tax_year", year))
    runs, slots, over = plan.runs, plan.slots, plan.over
    raws = [r.raws[(spec.variable, pid)] for r in runs]
    states: set[State] = set().union(*(r.states for r in raws))
    facts = sorted(set().union(*(r.facts for r in raws)))
    deps = sorted(set().union(*(r.deps for r in raws)))
    basis = sorted_unique(b for r in raws for b in r.basis)
    reasons = list(dict.fromkeys(x for r in raws for x in r.reasons))
    missing = {k: m for r in raws for k, m in r.missing.items()}
    if index is not None and all(isinstance(r.inputs, int) for r in raws):
        used_bits = 0
        for r in raws:
            used_bits |= r.inputs
        ix = index

        def hits(a: Any) -> int:
            return (a if isinstance(a, int) else ix.from_set(frozenset(a))) & used_bits

        relevant = [s for s in slots if hits(plan.affected.get(s.id, 0))]
    else:
        used_inputs = frozenset().union(*(r.inputs for r in raws))
        relevant = [s for s in slots if frozenset(plan.affected.get(s.id, ())) & used_inputs]
    undetermined: Undetermined | None = None
    evaluated: tuple = ()
    value: Any = None
    reason: OutOfScopeReason | None = None
    if reasons:
        states.add(State.OUT_OF_SCOPE)
        reason = _merge_reasons(reasons)
        basis = ()
    elif missing and (over is None or not slots):
        states.add(State.UNDETERMINED)
        undetermined = Undetermined(splits=tuple(missing[k] for k in sorted(missing)), outcomes=())
    elif over is not None and slots:
        # 依存する分かれ目だけで組合せが上限を超える：計算せず、依存する分かれ目の全部を「何を入力すれば決まるか」にする。
        # 注入されていない注入点にも依存するなら、その分かれ目を前に並べる（以前は注入の分かれ目だけを出し、評価しなかった
        # 分かれ目が「何を入力すれば決まるか」に出なかった。2026-11-12 の4回目）
        states.add(State.UNDETERMINED)
        undetermined = Undetermined(
            splits=tuple(missing[k] for k in sorted(missing)) + tuple(
                Split(
                    id=s.id,
                    means=s.means,
                    target={**dict(s.target), "評価しなかった理由": f"候補の組合せが {over.count} 通りで上限 {over.limit} を超える"},
                    candidates=tuple(c.label for c in s.candidates),
                    splits_conclusion=True,
                )
                for s in slots
            ),
            outcomes=(),
        )
    else:
        merged = _merge_values(relevant, slots, runs, spec.variable, pid, amount=spec.value_type == "円")
        evaluated = merged.evaluated
        if merged.undetermined is not None:
            states.add(State.UNDETERMINED)
            undetermined = merged.undetermined
        else:
            value = _to_value(merged.value, spec.value_type)
    return ResultValue(
        id=vid(spec.concept, pid),
        concept=spec.concept,
        variable=spec.variable,
        person=pid,
        time=tof(spec.concept),
        value=value,
        states=frozenset(states),
        basis=tuple(basis),
        depends_on=tuple(deps),
        facts=tuple(facts),
        undetermined=undetermined,
        out_of_scope=reason,
        filing_item=spec.filing_item and any(r.has_records for r in raws),
        filing_scope=spec.filing_scope,
        evaluated=evaluated,
    )


def _merge_values(
    relevant: list[Slot], slots: list[Slot], runs: list[_Run], var: str, pid: str, *, amount: bool | None = None
) -> Merged:
    """関係する分かれ目だけで候補ごとの値をまとめる。関係しない分かれ目で値が違えば（依存の読み落とし）全部の分かれ目でまとめる。"""
    projected: dict[tuple[str, ...], tuple[Assignment, Any]] = {}
    consistent = True
    for r in runs:
        key = tuple(r.assignment[s.id].label for s in relevant)
        a = {s.id: r.assignment[s.id] for s in relevant}
        v = r.raws[(var, pid)].value
        if key in projected and projected[key][1] != v:
            consistent = False
            break
        projected.setdefault(key, (a, v))
    if consistent:
        return merge(relevant, list(projected.values()), amount=amount)
    return merge(slots, [(r.assignment, r.raws[(var, pid)].value) for r in runs], amount=amount)


def _boundaries(
    by_key: Mapping[tuple[str | None, str | None], ResultValue], persons: list[str], unit: Unit, reg: Registry
) -> list[Boundary]:
    """境目の説明（結果に出した判定と比べる量の値があるものだけ）。ID の時点の部分は判定の値の時点（Unit.tag）。"""
    out: list[Boundary] = []
    for judgment_var, compared_var, criterion_name, concept, criterion_comparison in reg.boundaries:
        for pid in persons:
            jv = by_key.get((judgment_var, pid))
            cv = by_key.get((compared_var, pid))
            if jv is None or cv is None:
                continue  # この単位で出さない値
            time = jv.time
            if not isinstance(jv.value, Flag) or not isinstance(cv.value, YenAmount):
                continue  # 対象外・未確定・幅のときは出さない
            states = jv.states | cv.states
            if criterion_comparison is None:
                crit = next(b for b in jv.basis if b.type is BasisType.PARAMETER and b.name == criterion_name)
                comparison = Comparison.from_label(crit.detail["比較"])  # type: ignore[index]
                c = crit.value
            else:
                # 基準の概念（基準が判定日・年齢・制度などで変わる）：基準の値と、その値を決めたパラメータの根拠（値が同じもの）
                kv = by_key.get((criterion_name, pid))
                if kv is None or not isinstance(kv.value, YenAmount):
                    continue
                comparison = Comparison.from_label(criterion_comparison)
                c = kv.value.amount
                crit = criterion_basis(kv, c)
                states = states | kv.states
            current = cv.value.amount
            crossing = comparison.crossing_value(current, c)
            out.append(
                Boundary(
                    id=f"b:{unit.tag(time)}:{pid}:{concept}",
                    concept=concept,
                    person=pid,
                    time=time,
                    judgment_value_id=jv.id,
                    judgment=jv.value.value,
                    compared_value_id=cv.id,
                    compared_concept=cv.concept,
                    current=current,
                    criterion=crit,
                    criterion_value=c,
                    comparison=comparison,
                    crossing_value=crossing,
                    difference=crossing - current,
                    states=states,
                )
            )
    return out


def _reference_day(reference: str, unit: Unit, person: Mapping[str, Any]) -> _dt.date | None:
    """年齢の境目の判定の日（concepts.AGE_REFERENCE_DAYS。その日の終了時の年齢で比べる）。この単位で決まらなければ None。

    「その年」は situation の年（所得の年分）。死亡の時の現況は、死亡の時がその日の途中なので前日の終了時の年齢
    （所得税.年齢 の式と同じ読み：personal_deductions の classify.py）。
    """
    year_end = _dt.date(unit.income_year, 12, 31)
    if reference == "その年12月31日":
        return year_end
    if reference == "その年12月31日（死亡の時はその前日）":
        death = _dt.date.fromisoformat(person["death_on"]) if person.get("death_on") else None
        return death - _dt.timedelta(days=1) if death is not None and death <= year_end else year_end
    if unit.on is None:
        return None  # 判定日の単位でない
    if reference == "判定日":
        return unit.on
    if reference == "判定日の属する年の12月31日":
        return _dt.date(unit.on.year, 12, 31)
    raise ValueError(f"知らない判定の日: {reference}")


def _age_boundaries(
    by_key: Mapping[tuple[str | None, str | None], ResultValue],
    persons: list[str],
    unit: Unit,
    reg: Registry,
    ir: Mapping[str, Any],
    system: OkuraTaxBenefitSystem,
) -> list[AgeBoundary]:
    """年齢の境目の説明（2026-11-12。Registry.age_boundaries）。

    出すのは、宣言した概念の値と比べる年齢の値（整数で決まったもの）が結果にあり、生年月日と判定の日から求めた年齢が
    規則モジュールの年齢と同じ人だけ（違えば判定の日が別の日：出さない）。除く条件が真か決まらない人、判定日の下限より前の判定日も出さない。
    基準はパラメータの葉（その年分の1月1日の値。比較はメタデータ）か、宣言した年齢（根拠は宣言した概念の定義）。
    """
    out: list[AgeBoundary] = []
    if not getattr(reg, "age_boundaries", ()):
        return out
    people = {p["id"]: p for p in ir["persons"]}
    instant = f"{unit.income_year}-01-01"
    for spec in reg.age_boundaries:
        related = reg.dictionary.by_variable(spec.related_variable)
        if spec.criterion is not None:
            crit = parameter_basis(system.parameters, spec.criterion, instant)
            comparison = Comparison.from_label(crit.detail["比較"])  # type: ignore[index]
            limit = crit.value
        else:
            assert related is not None and spec.age_value is not None and spec.comparison is not None
            comparison = Comparison.from_label(spec.comparison)
            limit = spec.age_value
            crit = BasisEntry(
                type=BasisType.RULE,
                name=spec.boundary_id,
                source_kind=related.definition.source_kind,
                references=related.definition.references,
                law=related.definition.law,
                value=limit,
                detail={"比較": spec.comparison},
            )
        if spec.from_param is not None:
            start = _dt.date.fromisoformat(str(parameter_basis(system.parameters, spec.from_param, instant).value))
            if unit.on is None or unit.on < start:
                continue  # 判定日が区分の適用開始日より前（その年齢の区分を使わない）
        threshold = limit + (1 if comparison in (Comparison.AT_MOST, Comparison.MORE_THAN) else 0)
        for pid in persons:
            rv = by_key.get((spec.related_variable, pid))
            av = by_key.get((spec.age_variable, pid))
            if rv is None or av is None or not isinstance(av.value, Count):
                continue
            states = av.states
            if spec.exclude_variable is not None:
                ev = by_key.get((spec.exclude_variable, pid))
                if ev is None or not isinstance(ev.value, Flag) or ev.value.value:
                    continue
                states = states | ev.states
            ref = _reference_day(spec.reference, unit, people[pid])
            if ref is None:
                continue
            birth = _dt.date.fromisoformat(people[pid]["birth_on"])
            age = age_at_end_of(birth, ref)
            if age != av.value.value:
                continue  # 規則モジュールの年齢が別の日の年齢（判定する人の判定の時など）：この判定の日では説明しない
            boundary_on = attained_on(birth, threshold)
            out.append(
                AgeBoundary(
                    id=f"b:{unit.tag(rv.time)}:{pid}:{spec.boundary_id}",
                    concept=spec.boundary_id,
                    person=pid,
                    time=rv.time,
                    related_value_id=rv.id,
                    related_concept=rv.concept,
                    age_value_id=av.id,
                    age_concept=av.concept,
                    age=age,
                    birth_on=birth,
                    reference_on=ref,
                    reference=spec.reference,
                    criterion=crit,
                    criterion_value=limit,
                    comparison=comparison,
                    holds=comparison.holds(age, limit),
                    crossing_age=comparison.crossing_value(age, limit),
                    boundary_on=boundary_on,
                    days_to_boundary=(boundary_on - ref).days,
                    states=states,
                )
            )
    return out


def criterion_basis(criterion_value: ResultValue, amount: int) -> Any:
    """基準の概念の値の根拠のうち、基準の額を決めたもの（同じ値のパラメータの根拠）。なければ基準の概念の値そのものを根拠にする。"""
    for b in criterion_value.basis:
        if b.type is BasisType.PARAMETER and b.value == amount:
            return b
    from .basis import INJECTION_ONLY_KINDS, BasisEntry, SourceKind

    # 2026-11-13：基準の額が注入データ（級地など）で決まるとき、根拠に「自治体の資料」（注入データの出典にだけ使える種類）が混じる。
    # 基準の根拠（RULE）の種類はそれを除いて選ぶ（前は注入データを渡すと BasisEntry の検査で evaluate が例外で止まった。
    # 実際の家庭を通したときに見つけた：docs/measurements/20261113_family-run_findings.md）
    kinds = [b.source_kind for b in criterion_value.basis if b.source_kind is not None and b.source_kind not in INJECTION_ONLY_KINDS]
    return BasisEntry(
        BasisType.RULE,
        criterion_value.concept,
        kinds[0] if kinds else SourceKind.LAW,
        tuple(r for b in criterion_value.basis for r in b.references),
        value=amount,
        detail={"value_id": criterion_value.id},
    )

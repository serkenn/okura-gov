"""テストの道具の規則モジュール（法令の規則ではない）。登録の仕組みが、共有のファイルを触らずにモジュールを足せることを確かめる。

- test_decisions：判断.生計を一にする（先頭の人と、ほかの人の組）を1か所ずつ宣言し、入力変数に写す。扶養の目安
  （生計を一にし、かつ扶養親族の合計所得金額要件を満たす）と、仮置きの変数（年齢・事業所得の金額）を引く変数を持つ。
- test_rounding：根拠のない端数（給与等の収入金額の3分の1）を RoundingSlotSpec で候補の全部で評価する。
- test_groups：法律婚のグループを婚姻の記録（印つき）から組み立て、人をまたぐ依存（相手の合計所得金額）と、変数を引かずに
  グループの組み方だけを使う値（人数）を持つ（状態の伝搬の確かめ）。
- test_coverage：対象外の伝わり方（集め忘れの検出・途中の変数の対象外・ほかの年分の値）。
- test_stages・test_cycle・test_misdeclared：段階評価（D23 K1）。前の段の値と関係から入力・グループを書く段、段の順序、
  状態・根拠の伝搬、循環の検出、宣言のない依存の検出。
- test_parts・test_parts_cross：候補の評価を人のつながりごとに行うこと。
- test_monotone：単調な判断の両端評価（D21 R6）。
- test_windows：build_inputs の窓口（パラメータ・端数の候補・提出日・段の値）、年分別の根拠。
- test_injection：注入データの窓口（InjectionSpec・YearContext.injection）。年度の窓口があるときだけ、住民票の市町村の
  級地（候補のある注入点）と均等割の税率（候補のない注入点）を読む。

概念辞書の項目は tests/fixtures/rules/<名前>/concepts.yaml。
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from fractions import Fraction
from pathlib import Path

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from okura_core.basis import BasisEntry, BasisType, SourceKind
from okura_core.country import OkuraTaxBenefitSystem, build_system
from okura_core.country.entities import 人物
from okura_core.registry import (
    CheckContext,
    DecisionSlot,
    InjectionSlot,
    InjectionSpec,
    injection_key,
    Exclusion,
    GroupInstance,
    DecisionSpec,
    ModuleInputs,
    RecordKind,
    Registry,
    RoundingSlotSpec,
    RuleModule,
    StageContext,
    StageOutput,
    StageSpec,
    YearContext,
    build_registry,
)
from okura_core.result import OutOfScopeCategory, OutOfScopeReason, State
from okura_core.rounding import FUNCTIONS
from okura_core.rules import MODULES

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rules"
V_SEIKEI = "所得税_試験_申告者と生計を一にする"


class 所得税_試験_申告者と生計を一にする(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_扶養の目安(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_申告者と生計を一にする", period) * 人("所得税_扶養親族の合計所得金額要件", period)


class 所得税_試験_年齢を使う(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_未実装の区分", period)


class 所得税_試験_事業所得を使う(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_未実装の所得", period)


def _slots(ctx: YearContext) -> list[DecisionSlot]:
    if len(ctx.persons) < 2:
        return []
    head = ctx.persons[0]
    return [
        DecisionSlot(
            key=f"{head}:{q}",
            target={"person": head, "other_person": q},
            matches=lambda r, q=q: r["subject"]["person"] == head and r["subject"]["other_person"] == q,
        )
        for q in ctx.persons[1:]
    ]


def _decision_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    head = ctx.persons[0]
    for p in ctx.persons:
        if p == head:
            out.set(V_SEIKEI, p, False)
            continue
        d = ctx.decision("判断.生計を一にする", f"{head}:{p}")
        out.set(V_SEIKEI, p, bool(d.value), d.record_ids, d.states)
    return out


TEST_DECISIONS = RuleModule(
    name="test_decisions",
    title="試験：判断の候補評価",
    directory=FIXTURES / "test_decisions",
    variables=(所得税_試験_申告者と生計を一にする, 所得税_試験_扶養の目安, 所得税_試験_年齢を使う, 所得税_試験_事業所得を使う),
    build_inputs=_decision_inputs,
    decisions=(DecisionSpec(kind="判断.生計を一にする", slots=_slots),),
)


class 所得税_試験_端数の候補(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_三分の一(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        収入 = 人("所得税_給与等の収入金額", period)
        候補 = 人("所得税_試験_端数の候補", period)
        return np.array([FUNCTIONS[str(c)](Fraction(int(x), 3)) for x, c in zip(収入, 候補)], dtype=np.int32)


class 所得税_試験_三分の一が基準以下(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_三分の一", period) <= 333_333


TEST_ROUNDING = RuleModule(
    name="test_rounding",
    title="試験：根拠のない端数",
    directory=FIXTURES / "test_rounding",
    variables=(所得税_試験_端数の候補, 所得税_試験_三分の一, 所得税_試験_三分の一が基準以下),
    roundings=(RoundingSlotSpec(name="試験の3分の1", variable="所得税_試験_端数の候補", title="試験の端数"),),
)


class 所得税_試験_連鎖の端数の候補A(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_連鎖の端数の候補B(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_連鎖の値(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        収入 = [int(x) for x in 人("所得税_給与等の収入金額", period)]
        a = [FUNCTIONS[str(c)](Fraction(x, 2)) for x, c in zip(収入, 人("所得税_試験_連鎖の端数の候補A", period))]
        if not any(v % 2 == 0 and v > 0 for v in a):  # Aの丸めの結果が奇数ならBの候補を引かない
            return np.array([v * 10 for v in a], dtype=np.int32)
        b = [FUNCTIONS[str(c)](Fraction(v, 4)) for v, c in zip(a, 人("所得税_試験_連鎖の端数の候補B", period))]
        return np.array([v * 10 + w for v, w in zip(a, b)], dtype=np.int32)


TEST_ROUNDING_CHAIN = RuleModule(
    name="test_rounding_chain",
    title="試験：候補によって引かれる端数",
    directory=FIXTURES / "test_rounding_chain",
    variables=(所得税_試験_連鎖の端数の候補A, 所得税_試験_連鎖の端数の候補B, 所得税_試験_連鎖の値),
    roundings=(
        RoundingSlotSpec(name="試験の連鎖A", variable="所得税_試験_連鎖の端数の候補A", title="試験の端数A"),
        RoundingSlotSpec(name="試験の連鎖B", variable="所得税_試験_連鎖の端数の候補B", title="試験の端数B"),
    ),
)


class 所得税_試験_相手の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人.法律婚.sum(人("所得税_合計所得金額", period)) - 人("所得税_合計所得金額", period)


class 所得税_試験_法律婚の人数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人.法律婚.nb_persons()


def _marriages(ctx: YearContext) -> list[GroupInstance]:
    out: list[GroupInstance] = []
    paired: set[str] = set()
    for r in sorted(ctx.records("marriage"), key=lambda r: r["id"]):
        a, b = r["roles"]["spouse_a"], r["roles"]["spouse_b"]
        if a in ctx.persons and b in ctx.persons and not ({a, b} & paired):
            states = frozenset({State.from_mark(r["mark"])}) if "mark" in r else frozenset()
            out.append(GroupInstance(f"法律婚:{r['id']}", {"配偶者一覧": (a, b)}, (r["id"],), states))
            paired |= {a, b}
    return out + [GroupInstance(f"法律婚:{p}", {"配偶者一覧": (p,)}) for p in ctx.persons if p not in paired]


TEST_GROUPS = RuleModule(
    name="test_groups",
    title="試験：グループと人をまたぐ依存",
    directory=FIXTURES / "test_groups",
    variables=(所得税_試験_相手の合計所得金額, 所得税_試験_法律婚の人数),
    record_kinds=frozenset({"marriage"}),
    groups={"法律婚一覧": _marriages},
)

#: test_coverage が途中の変数を対象外にする給与等の収入金額（試験の目印）。
MARK_WAGES = 1_234_567


class 所得税_試験_一時の受取(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_集めない所得(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_一時の受取", period)


class 所得税_試験_中間(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_給与所得", period)


class 所得税_試験_中間を使う(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_中間", period)


class 所得税_試験_前年の給与等の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_給与等の収入金額", period.last_year)


def _windfall_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    for p in ctx.persons:
        ids = [r["id"] for r in ctx.records("windfall_receipt") if r["roles"]["recipient"] == p]
        out.set("所得税_試験_一時の受取", p, 0, ids)
        if ids:
            out.exclude(p, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "試験：受取を対象外にする", tuple(ids)), "所得税_試験_一時の受取")
    return out


def _mark_check(ctx: CheckContext):
    wages = ctx.calc("所得税_給与等の収入金額")
    for i, p in enumerate(ctx.persons):
        if int(wages[i]) == MARK_WAGES:
            yield Exclusion(p, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "試験：途中の変数を対象外にする"), "所得税_試験_中間")


TEST_COVERAGE = RuleModule(
    name="test_coverage",
    title="試験：対象外の伝わり方",
    directory=FIXTURES / "test_coverage",
    variables=(所得税_試験_一時の受取, 所得税_試験_集めない所得, 所得税_試験_中間, 所得税_試験_中間を使う, 所得税_試験_前年の給与等の収入金額),
    record_kinds=frozenset({"windfall_receipt"}),
    build_inputs=_windfall_inputs,
    checks=(_mark_check,),
)


# ---------------------------------------------------------------------------
# 段階評価（D23 K1）
# ---------------------------------------------------------------------------

V_WAGE = "所得税_給与等の収入金額"
V_FLAG = "所得税_試験_相手の給与が基準以下か"
V_SECOND = "所得税_試験_二段目の旗"
V_BRANCH = "所得税_試験_判断の分岐の旗"
#: 試験の道具の規則の根拠。
STAGE_RULE = BasisEntry(
    type=BasisType.RULE,
    name="試験：相手の給与で決める規則",
    source_kind=SourceKind.LAW,
    references=("docs/public-sources/20261109_R4-modeling_concepts.md#3.2",),
    law="試験の道具",
)
#: test_stages の段の基準（試験の道具の値）。
SPOUSE_WAGE_LIMIT = 1_000_000
#: 第2段の値から書く段の規則の根拠（段の根拠が依存する値へ伝わることを確かめる）。
SECOND_RULE = BasisEntry(
    type=BasisType.RULE,
    name="試験：第2段の値で決める規則",
    source_kind=SourceKind.LAW,
    references=("docs/public-sources/20261109_R4-modeling_concepts.md#3.2",),
    law="試験の道具",
)


class 所得税_試験_相手の給与が基準以下か(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_段階の控除(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人(V_FLAG, period) * 100_000


class 所得税_試験_二段目の旗(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_二段目の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人(V_SECOND, period) * 30_000


class 所得税_試験_段階の法律婚の人数(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人.法律婚.nb_persons()


class 所得税_試験_判断の分岐の旗(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


def _spouse_stage(ctx: StageContext) -> StageOutput:
    """婚姻の相手の給与等の収入金額が基準以下か（ほかの人の値を前の段から読む）。"""
    out = StageOutput()
    on = dt.date(ctx.year, 12, 31)
    for p in ctx.persons:
        spouses = ctx.relations.spouses(p, on)
        if not spouses:
            out.set(V_FLAG, p, False, uses=())
            continue
        r = spouses[0]
        v = ctx.value(V_WAGE, r.other)
        out.set(V_FLAG, p, v.value <= SPOUSE_WAGE_LIMIT, record_ids=(r.record_id,), states=r.states, uses=[v])
    return out


def _second_stage(ctx: StageContext) -> StageOutput:
    """第2段の値（段階の控除）から書く入力。"""
    out = StageOutput()
    for p in ctx.persons:
        v = ctx.value("所得税_試験_段階の控除", p)
        out.set(V_SECOND, p, v.value > 0, uses=[v])
    return out


def _marriage_stage(ctx: StageContext) -> StageOutput:
    """法律婚のグループを関係の窓口から組み立てる。"""
    out = StageOutput()
    on = dt.date(ctx.year, 12, 31)
    seen: set[str] = set()
    insts: list[GroupInstance] = []
    for p in ctx.persons:
        if p in seen:
            continue
        spouses = [r for r in ctx.relations.spouses(p, on) if r.other in ctx.persons and r.other not in seen]
        if spouses:
            r = spouses[0]
            uses = [ctx.value(V_WAGE, p), ctx.value(V_WAGE, r.other)]
            insts.append(GroupInstance(f"法律婚:{r.record_id}", {"配偶者一覧": (p, r.other)}, (r.record_id,), r.states, uses=uses))
            seen |= {p, r.other}
        else:
            insts.append(GroupInstance(f"法律婚:{p}", {"配偶者一覧": (p,)}, uses=()))
            seen.add(p)
    out.group("法律婚一覧", insts)
    return out


def _branch_stage(ctx: StageContext) -> StageOutput:
    """未入力の判断（候補の値）で分かれる入力を書く：候補の評価が段階をまたぐことを確かめる。"""
    out = StageOutput()
    head = ctx.persons[0]
    for p in ctx.persons:
        if p == head or len(ctx.persons) < 2:
            out.set(V_BRANCH, p, False, uses=())
            continue
        d = ctx.decision("判断.生計を一にする", f"{head}:{p}")
        v = ctx.value(V_WAGE, p)
        out.set(V_BRANCH, p, bool(d.value) and v.value > 0, record_ids=d.record_ids, states=d.states, uses=[v])
    return out


def _stage_slots(ctx: YearContext) -> list[DecisionSlot]:
    if len(ctx.persons) < 2:
        return []
    head = ctx.persons[0]
    return [
        DecisionSlot(
            key=f"{head}:{q}",
            target={"person": head, "other_person": q},
            matches=lambda r, q=q: r["subject"]["person"] == head and r["subject"]["other_person"] == q,
        )
        for q in ctx.persons[1:]
    ]


TEST_STAGES = RuleModule(
    name="test_stages",
    title="試験：段階評価",
    directory=FIXTURES / "test_stages",
    variables=(
        所得税_試験_相手の給与が基準以下か,
        所得税_試験_段階の控除,
        所得税_試験_二段目の旗,
        所得税_試験_二段目の額,
        所得税_試験_段階の法律婚の人数,
        所得税_試験_判断の分岐の旗,
    ),
    record_kinds=frozenset({"marriage"}),
    decisions=(DecisionSpec(kind="判断.生計を一にする", slots=_stage_slots),),
    stages=(
        StageSpec(name="試験_二段目", title="試験：第2段の値から書く", reads=("所得税_試験_段階の控除",), writes=(V_SECOND,), run=_second_stage, basis=(SECOND_RULE,)),
        StageSpec(name="試験_相手の給与", title="試験：相手の給与で決める", reads=(V_WAGE,), writes=(V_FLAG,), run=_spouse_stage, basis=(STAGE_RULE,)),
        StageSpec(name="試験_法律婚の組み立て", title="試験：法律婚を組み立てる", reads=(V_WAGE,), groups=("法律婚一覧",), run=_marriage_stage),
        StageSpec(name="試験_判断の分岐", title="試験：判断で分かれる", reads=(V_WAGE,), writes=(V_BRANCH,), run=_branch_stage),
    ),
)


class 所得税_試験_循環A(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_循環B(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_Aの値(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_循環A", period)


class 所得税_試験_Bの値(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人("所得税_試験_循環B", period)


def _never(ctx: StageContext) -> StageOutput:
    raise AssertionError("循環した段は実行しない")


#: 段Aは段Bの値を読み、段Bは段Aの値を読む（循環）。
TEST_CYCLE = RuleModule(
    name="test_cycle",
    title="試験：段階の循環",
    directory=FIXTURES / "test_cycle",
    variables=(所得税_試験_循環A, 所得税_試験_循環B, 所得税_試験_Aの値, 所得税_試験_Bの値),
    stages=(
        StageSpec(name="試験_循環の段A", title="試験", reads=("所得税_試験_Bの値",), writes=("所得税_試験_循環A",), run=_never),
        StageSpec(name="試験_循環の段B", title="試験", reads=("所得税_試験_Aの値",), writes=("所得税_試験_循環B",), run=_never),
    ),
)


class 所得税_試験_宣言のない入力(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_宣言のない依存の値(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):  # 概念辞書に宣言していない依存（段の値と最後の計算が違うことの検出を確かめる）
        return 人("所得税_試験_宣言のない入力", period)


class 所得税_試験_宣言のない依存の読み(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


def _write_misdeclared(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    for p in ctx.persons:
        v = ctx.value(V_WAGE, p)
        out.set("所得税_試験_宣言のない入力", p, v.value, uses=[v])
    return out


def _read_misdeclared(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    for p in ctx.persons:
        v = ctx.value("所得税_試験_宣言のない依存の値", p)
        out.set("所得税_試験_宣言のない依存の読み", p, v.value, uses=[v])
    return out


TEST_MISDECLARED = RuleModule(
    name="test_misdeclared",
    title="試験：宣言のない依存の検出",
    directory=FIXTURES / "test_misdeclared",
    variables=(所得税_試験_宣言のない入力, 所得税_試験_宣言のない依存の値, 所得税_試験_宣言のない依存の読み),
    stages=(
        StageSpec(name="試験_宣言のない入力を書く", title="試験", reads=(V_WAGE,), writes=("所得税_試験_宣言のない入力",), run=_write_misdeclared),
        StageSpec(name="試験_宣言のない依存を読む", title="試験", reads=("所得税_試験_宣言のない依存の値",), writes=("所得税_試験_宣言のない依存の読み",), run=_read_misdeclared),
    ),
)

# ---------------------------------------------------------------------------
# 候補の評価を人のつながりごとに
# ---------------------------------------------------------------------------

V_LINK = "所得税_試験_つながりの判断"


class 所得税_試験_つながりの判断(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


def _marriage_pairs(ctx: YearContext) -> list[tuple[str, str]]:
    return sorted(
        (r["roles"]["spouse_a"], r["roles"]["spouse_b"])
        for r in ctx.records("marriage")
        if r["roles"]["spouse_a"] in ctx.persons and r["roles"]["spouse_b"] in ctx.persons
    )


def _part_slots(ctx: YearContext) -> list[DecisionSlot]:
    return [
        DecisionSlot(
            key=f"{a}:{b}",
            target={"person": a, "other_person": b},
            matches=lambda r, a=a, b=b: r["subject"]["person"] == a and r["subject"]["other_person"] == b,
        )
        for a, b in _marriage_pairs(ctx)
    ]


def _part_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    decided: dict[str, bool] = {}
    for a, b in _marriage_pairs(ctx):
        d = ctx.decision("判断.生計を一にする", f"{a}:{b}")
        decided[a] = bool(d.value)
    for p in ctx.persons:
        out.set(V_LINK, p, decided.get(p, False))
    return out


TEST_PARTS = RuleModule(
    name="test_parts",
    title="試験：人のつながりごとの候補の評価",
    directory=FIXTURES / "test_parts",
    variables=(所得税_試験_つながりの判断,),
    record_kinds=frozenset({"marriage"}),
    build_inputs=_part_inputs,
    decisions=(DecisionSpec(kind="判断.生計を一にする", slots=_part_slots),),
)

V_HEAD_WAGE = "所得税_試験_先頭の人の給与"
V_OWN_JUDGMENT = "所得税_試験_人の判断"


class 所得税_試験_先頭の人の給与(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_人の判断(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"


def _own_slots(ctx: YearContext) -> list[DecisionSlot]:
    return [
        DecisionSlot(key=p, target={"person": p}, matches=lambda r: False, persons=(p,))
        for p in ctx.persons[1:]
    ]


def _own_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    for p in ctx.persons:
        if p == ctx.persons[0]:
            out.set(V_OWN_JUDGMENT, p, False)
        else:
            out.set(V_OWN_JUDGMENT, p, bool(ctx.decision("判断.生計を一にする", p).value))
    return out


def _head_wage_stage(ctx: StageContext) -> StageOutput:
    out = StageOutput()
    v = ctx.value(V_WAGE, ctx.persons[0])
    for p in ctx.persons:
        out.set(V_HEAD_WAGE, p, v.value, uses=[v])
    return out


TEST_PARTS_CROSS = RuleModule(
    name="test_parts_cross",
    title="試験：段の読みが人のつながりをまたぐ",
    directory=FIXTURES / "test_parts_cross",
    variables=(所得税_試験_先頭の人の給与, 所得税_試験_人の判断),
    build_inputs=_own_inputs,
    decisions=(DecisionSpec(kind="判断.生計を一にする", slots=_own_slots),),
    stages=(StageSpec(name="試験_先頭の人の給与を読む", title="試験", reads=(V_WAGE,), writes=(V_HEAD_WAGE,), run=_head_wage_stage),),
)

# ---------------------------------------------------------------------------
# 単調な判断の両端評価
# ---------------------------------------------------------------------------

V_MONO = "所得税_試験_単調の額"
#: test_monotone の判定の基準（試験の道具の値）。
MONO_LIMIT = 300_000


class 所得税_試験_単調の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_単調の判定(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "試験"

    def formula(人, period, parameters):
        return 人(V_MONO, period) <= MONO_LIMIT


def _windfalls(ctx: YearContext, p: str) -> list:
    return [r for r in ctx.records("windfall_receipt") if r["roles"]["recipient"] == p and r["when"]["on"].startswith(str(ctx.year))]


def _mono_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    for p in ctx.persons:
        for r in _windfalls(ctx, p):
            out.append(
                DecisionSlot(
                    key=r["id"],
                    target={"record_id": r["id"]},
                    matches=lambda j, rid=r["id"]: j["subject"]["record_id"] == rid,
                    monotone=f"試験単調:{p}",
                )
            )
    return out


def _mono_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    for p in ctx.persons:
        total = 0
        ids: list[str] = []
        states: set[State] = set()
        for r in _windfalls(ctx, p):
            d = ctx.decision("判断.業務関連性", r["id"])
            if d.value:
                total += r["amounts"]["amount"]
            ids += [r["id"], *d.record_ids]
            states |= d.states
        out.set(V_MONO, p, total, ids, states)
    return out


TEST_MONOTONE = RuleModule(
    name="test_monotone",
    title="試験：単調な判断の両端評価",
    directory=FIXTURES / "test_monotone",
    variables=(所得税_試験_単調の額, 所得税_試験_単調の判定),
    record_kinds=frozenset({"windfall_receipt"}),
    build_inputs=_mono_inputs,
    decisions=(DecisionSpec(kind="判断.業務関連性", slots=_mono_slots),),
)

# ---------------------------------------------------------------------------
# build_inputs の窓口・年分別の根拠
# ---------------------------------------------------------------------------

V_WINDOW = "所得税_試験_窓口の額"
V_MONTH = "所得税_試験_提出月"
V_THIRD = "所得税_試験_給与の三分の一の丸め"
V_COPY = "所得税_試験_相手の給与の写し"
WINDOW_ROUNDING = "試験_窓口の端数"
YEARLY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="試験：令和8年分だけの規則",
    source_kind=SourceKind.LAW,
    references=("docs/public-sources/20261109_R4-modeling_concepts.md#4.1",),
    law="試験の道具",
)


class 所得税_試験_窓口の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_提出月(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_給与の三分の一の丸め(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 所得税_試験_相手の給与の写し(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


def _window_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    base = ctx.parameters.所得税.所得金額調整控除.第1項の給与等の収入金額の基準
    mid = ctx.parameters_at(dt.date(ctx.year, 6, 1)).所得税.所得金額調整控除.第1項の給与等の収入金額の基準
    assert int(base) == int(mid)
    month = ctx.filing_date.on.month if ctx.filing_date is not None else 0
    for p in ctx.persons:
        out.set(V_WINDOW, p, int(base), basis=(ctx.parameter_basis("所得税.所得金額調整控除.第1項の給与等の収入金額の基準"),))
        out.set(V_MONTH, p, month)
        wages = sum(r["amounts"]["gross"] for r in ctx.records("salary_payment") if r["roles"]["recipient"] == p and r["when"]["on"].startswith(str(ctx.year)))
        third = ctx.round_unfounded(WINDOW_ROUNDING, Fraction(wages, 3)) if wages % 3 else wages // 3
        out.set(V_THIRD, p, third)
        v = ctx.stage_value("試験_給与を読む", V_WAGE, p)
        out.set(V_COPY, p, 0 if v.pending else v.value, uses=None if v.pending else (v,))
    return out


TEST_WINDOWS = RuleModule(
    name="test_windows",
    title="試験：窓口",
    directory=FIXTURES / "test_windows",
    variables=(所得税_試験_窓口の額, 所得税_試験_提出月, 所得税_試験_給与の三分の一の丸め, 所得税_試験_相手の給与の写し),
    build_inputs=_window_inputs,
    record_kinds=frozenset({RecordKind("filed_document", "document_type", frozenset({"final_return"}))}),
    roundings=(RoundingSlotSpec(name=WINDOW_ROUNDING, variable=None, title="試験の端数（入力変数を持たない）"),),
    stages=(StageSpec(name="試験_給与を読む", title="試験", reads=(V_WAGE,), writes=(V_COPY,), run=None),),
    rules_by_year={2026: {V_WINDOW: (YEARLY_RULE,)}},
)


# ---------------------------------------------------------------------------
# test_injection
# ---------------------------------------------------------------------------

V_KYUCHI = "住民税_試験_級地の番号"
V_KINTOWARI = "住民税_試験_均等割の税率"


class 住民税_試験_級地の番号(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


class 住民税_試験_均等割の税率(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "試験"


def _municipality(ctx: YearContext, p: str, on: dt.date) -> str | None:
    for r in ctx.records("resident_record"):
        w = r["when"]
        if r["roles"]["person"] == p and w["from_on"] <= on.isoformat() and (not w.get("to_on") or on.isoformat() <= w["to_on"]):
            return r["attributes"]["municipality_code"]
    return None


def _injection_slots(point: str, date_name: str):
    def slots(ctx: YearContext) -> list[InjectionSlot]:
        w = ctx.window("住民税", "年度")
        if w is None:
            return []
        on = w.date(date_name)
        codes = sorted({c for p in ctx.persons if (c := _municipality(ctx, p, on)) is not None})
        return [InjectionSlot(injection_key("municipality", c, on), "municipality", c, on) for c in codes]

    return slots


def _injection_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    w = ctx.window("住民税", "年度")
    for p in ctx.persons:
        if w is None:
            out.set(V_KYUCHI, p, 0)
            out.set(V_KINTOWARI, p, 0)
            continue
        dec31, jan1 = w.date("前年の12月31日"), w.date("賦課期日")
        c = _municipality(ctx, p, dec31)
        if c is None:
            out.set(V_KYUCHI, p, 0)
        else:
            d = ctx.injection("住民税.級地", injection_key("municipality", c, dec31))
            out.set(V_KYUCHI, p, int(d.value["級地"][0]), d.record_ids, d.states, basis=d.basis, missing=d.missing)
        c = _municipality(ctx, p, jan1)
        if c is None:
            out.set(V_KINTOWARI, p, 0)
        else:
            d = ctx.injection("住民税.均等割の税率", injection_key("municipality", c, jan1))
            value = 0 if d.value is None else d.value["税率"]
            out.set(V_KINTOWARI, p, value, d.record_ids, d.states, basis=d.basis, missing=d.missing)
    return out


TEST_INJECTION = RuleModule(
    name="test_injection",
    title="試験：注入データ",
    directory=FIXTURES / "test_injection",
    variables=(住民税_試験_級地の番号, 住民税_試験_均等割の税率),
    build_inputs=_injection_inputs,
    record_kinds=frozenset({"resident_record"}),
    injections=(
        InjectionSpec("住民税.級地", _injection_slots("住民税.級地", "前年の12月31日")),
        InjectionSpec("住民税.均等割の税率", _injection_slots("住民税.均等割の税率", "賦課期日")),
    ),
)


@functools.cache
def fixture_registry(*names: str) -> Registry:
    extra = {
        "test_decisions": TEST_DECISIONS,
        "test_rounding": TEST_ROUNDING,
        "test_rounding_chain": TEST_ROUNDING_CHAIN,
        "test_groups": TEST_GROUPS,
        "test_coverage": TEST_COVERAGE,
        "test_stages": TEST_STAGES,
        "test_cycle": TEST_CYCLE,
        "test_misdeclared": TEST_MISDECLARED,
        "test_parts": TEST_PARTS,
        "test_parts_cross": TEST_PARTS_CROSS,
        "test_monotone": TEST_MONOTONE,
        "test_windows": TEST_WINDOWS,
        "test_injection": TEST_INJECTION,
    }
    added = tuple(extra[n] for n in names)
    # 道具が組み立てるグループ（法律婚）を登録済みのモジュールも組み立てるようになったら、道具の組み立てを使う
    # （道具は仕組みを確かめるもの。並行の担当がグループを実装しても、このテストの道具を直さずに済む）
    taken = {g for m in added for g in m.groups} | {g for m in added for st in m.stages for g in st.groups}
    real = tuple(
        dataclasses.replace(
            m,
            groups={g: b for g, b in m.groups.items() if g not in taken},
            stages=tuple(dataclasses.replace(st, groups=tuple(g for g in st.groups if g not in taken)) for st in m.stages),
        )
        for m in MODULES
    )
    return build_registry(real + added)


@functools.cache
def fixture_system(*names: str) -> OkuraTaxBenefitSystem:
    return build_system(fixture_registry(*names))

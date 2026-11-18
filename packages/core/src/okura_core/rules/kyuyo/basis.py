"""規則モジュール kyuyo の根拠：パラメータでない規則（RULES）と、給与所得の金額の根拠の組み立て（使った規定・表の行・端数処理だけ）。"""

from __future__ import annotations

from collections.abc import Mapping

from ...basis import BasisEntry, BasisType, SourceKind
from ...explain import parameter_basis
from ...registry import BasisContext
from .calc import KyuyoDetail, deduction_rules_from_parameters, kyuyo_deduction, kyuyo_shotoku, rules_from_parameters
from .tables import Beppyo5Table
from .tokutei import TOKUTEI_RULE, finish, tokutei_raw
from .uncollectible import CAP_RULE
from ...rounding import FUNCTIONS

INCOME_TOTAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="給与等の収入金額は、その年中の給与等の合計（支払者が複数でも合計に1回だけ規定を当てる）",
    source_kind=SourceKind.LAW,
    law="所得税法第28条第4項・租税特別措置法第29条の4第2項（「その年中の給与等の収入金額」）",
    references=(
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#1.1",
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#2.1",
        "docs/public-sources/20261109_impl-prep_kyuyo-sources.md#4.1",
    ),
    detail={"reading": ["docs/hypotheses/20261109_impl-prep_kyuyo-hypotheses.md#H7"]},
)

INCOME_YEAR_RULE = BasisEntry(
    type=BasisType.RULE,
    name="給与は、支給日（中間表現の attributes.due_on）の年分の収入金額に数える",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達36−9（給与所得の収入金額の収入すべき時期：契約・慣習等で定められた支給日。定めがないときは支給を受けた日）",
    references=(
        "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#1",
        "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#2.1",
    ),
)

#: 変数名 → その変数の値に付ける規則の根拠（パラメータはトレースから別に足す）。
RULES: Mapping[str, tuple[BasisEntry, ...]] = {
    "所得税_給与等の収入金額": (INCOME_TOTAL_RULE, INCOME_YEAR_RULE),
}


def table_row_basis(table: Beppyo5Table, detail: KyuyoDetail) -> BasisEntry:
    assert detail.table_row is not None
    return BasisEntry(
        type=BasisType.DATA,
        name=f"{table.title}（{table.table_id}）",
        source_kind=table.source_kind,
        references=table.references,
        law=table.law,
        value=detail.table_row.to_dict(),
        detail={
            "file": f"rules/kyuyo/data/{table.file_name}",
            "sha256": table.sha256,
            "law_revision": table.law_revision_id,
            "asof": table.asof,
        },
    )


def deduction_basis(ctx: BasisContext) -> list[BasisEntry]:
    """給与所得控除額の根拠（その人の収入金額で実際に使った規定だけ）。"""
    rules = deduction_rules_from_parameters(ctx.parameters)
    income = int(ctx.computed("所得税_給与等の収入金額")[ctx.index])
    detail = kyuyo_deduction(income, rules)
    return [parameter_basis(ctx.root, n, ctx.instant) for n in detail.parameter_names]


def kyuyo_basis(ctx: BasisContext) -> list[BasisEntry]:
    """給与所得の金額の根拠（その人の収入金額で実際に使った規定だけ）。OpenFisca の値と純粋関数の値が食い違えば誤り。"""
    rules = rules_from_parameters(ctx.parameters)
    income = int(ctx.computed("所得税_給与等の収入金額")[ctx.index])
    detail = kyuyo_shotoku(income, rules)
    details = [detail]
    # 特定支出控除（所法57の2①。KY-11、2026-11-12）：当てた人は第28条第2項の残額（措法29の4② の額）から超える部分を控除した額。
    # 1円未満は根拠のない端数の候補で丸めるので、候補のどれかと一致すればよい
    raw = None
    total = int(ctx.computed("所得税_特定支出の額の合計額")[ctx.index])
    if total > 0 and bool(ctx.computed("所得税_特定支出控除の適用を受けるか")[ctx.index]):
        raw = tokutei_raw(income, total, rules, deduction_rules_from_parameters(ctx.parameters))
    expected = {detail.value} if raw is None else {finish(raw, f) for f in FUNCTIONS.values()}
    # 所法64①・所令180②（KY-08）：回収不能額等のある人は、令180②一・二の低い方を引いた額（uncollectible.py）
    diff = int(ctx.computed("所得税_回収不能額等に係る給与所得の金額の差額")[ctx.index])
    if diff > 0:
        cap = int(ctx.computed("所得税_給与の回収不能額等の上限")[ctx.index])
        expected = {v - min(diff, cap) for v in expected}
        bad = int(ctx.computed("所得税_回収することができないこととなった給与等の金額")[ctx.index])
        details.append(kyuyo_shotoku(max(0, income - bad), rules))
    if int(ctx.computed("所得税_給与所得")[ctx.index]) not in expected:
        raise AssertionError(f"給与所得の金額が OpenFisca と純粋関数で食い違う: {ctx.person} {ctx.year}")
    out: list[BasisEntry] = []
    seen: set[str] = set()
    for d in details:
        for n in d.parameter_names:
            if n not in seen:
                seen.add(n)
                out.append(parameter_basis(ctx.root, n, ctx.instant))
        if d.table_row is not None:
            out.append(table_row_basis(rules.table, d))
        if d.rounding is not None:
            out.append(d.rounding.basis_entry())
    if raw is not None:
        for n in kyuyo_deduction(income, deduction_rules_from_parameters(ctx.parameters)).parameter_names:
            if n not in seen:
                seen.add(n)
                out.append(parameter_basis(ctx.root, n, ctx.instant))
        out.append(TOKUTEI_RULE)
    if diff > 0:
        out.append(CAP_RULE)
    return out

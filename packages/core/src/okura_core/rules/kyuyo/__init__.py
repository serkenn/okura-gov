"""規則モジュール kyuyo：給与所得（所得税法第28条・別表第五・第57条の2〔特定支出控除〕、租税特別措置法第29条の4）。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...registry import RecordKind, RoundingSlotSpec, RuleModule, StageSpec
from .basis import RULES, deduction_basis, kyuyo_basis
from .inputs import DECISIONS, STAGE_DEEMED, V_DEEMED, V_FAMILY_OUT, V_INCOME, V_RETIRE_SALARY, build_inputs
from .tokutei import ROUNDING as TOKUTEI_ROUNDING
from .tokutei import V_ROUNDING as V_TOKUTEI_ROUNDING
from .uncollectible import STAGE as UNCOLLECTIBLE_STAGE
from .variables import VARIABLES

MODULE = RuleModule(
    name="kyuyo",
    title="給与所得",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    record_kinds=frozenset(
        {"salary_payment", "commuting_status", "disability_basis", "specific_expense", RecordKind("withholding_slip", "slip_type", frozenset({"salary"}))}
    ),
    build_inputs=build_inputs,
    decisions=DECISIONS,
    roundings=(
        RoundingSlotSpec(
            name="給与所得控除額の1円未満",
            variable="所得税_給与所得控除額の端数の候補",
            title="給与所得控除額の1円未満の端数（所得税法第28条第3項に定めがない。家内労働者等の特例が引くときに使う）",
        ),
        RoundingSlotSpec(
            name=TOKUTEI_ROUNDING,
            variable=V_TOKUTEI_ROUNDING,
            title="特定支出控除（所得税法第57条の2第1項）を当てた給与所得の金額の1円未満の端数（定めがない。KY-11）",
        ),
    ),
    stages=(
        StageSpec(
            name=STAGE_DEEMED,
            title=(
                "事業専従者控除額のみなし給与（所得税法第57条第4項）と、退職手当等に当たらず給与とした支払を専従者・受給者の給与等の収入金額に足し、"
                "生計を一にする親族の事業から受けた給与のうち所得税法第56条でないものとみなす額を引く"
            ),
            reads=(V_DEEMED, V_FAMILY_OUT, V_RETIRE_SALARY),
            writes=(V_INCOME,),
            run=None,
        ),
        UNCOLLECTIBLE_STAGE,  # 所得税法第64条第1項・施行令第180条第2項（KY-08。uncollectible.py）
    ),
    rules=RULES,
    basis={"所得税_給与所得": kyuyo_basis, "所得税_給与所得控除額": deduction_basis},
)

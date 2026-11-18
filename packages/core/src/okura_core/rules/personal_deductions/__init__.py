"""規則モジュール personal_deductions：人的控除と扶養（人の区分・扶養などの判定・人的控除の額）。README.md を見る。

扶養の割当て（所令218〜220）と所得金額調整控除の対象の親族等は段階評価の段（allocation.py）で決める（D23 K1）。
"""

from __future__ import annotations

from pathlib import Path

from ...registry import RuleModule, StageSpec
from . import allocation as a
from .basis import ALLOCATION_RULE, CHAIN_RULE, HAS_RULE, RULES
from .checks import check_personal
from .inputs import DECISIONS, RECORD_KINDS, build_inputs
from .variables import VARIABLES

MODULE = RuleModule(
    name="personal_deductions",
    title="人的控除と扶養",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    record_kinds=RECORD_KINDS,
    build_inputs=build_inputs,
    decisions=DECISIONS,
    stages=(
        StageSpec(
            name=a.STAGE_HAS,
            title="所得金額調整控除の第1項の親族等を有するか（第1段の値から人ごとに決める）",
            reads=(a.R_JUDGE, a.R_AGE, a.R_SPECIAL, a.R_WAGE),
            writes=(a.V_HAS,),
            run=a.run_has,
            basis=(HAS_RULE,),
        ),
        StageSpec(
            name=a.STAGE_ALLOC,
            title="扶養の割当てと法律婚（所令218〜220 の重複の解消）",
            reads=(a.R_TOTAL, a.R_AGE, a.R_RESIDENT, a.R_GROSS, a.R_RETIRE, a.R_DIV, a.R_GAIN, a.R_SPECIAL, a.R_DISABLED),
            writes=a.ALLOC_WRITES,
            groups=("扶養所属一覧", "法律婚一覧"),
            run=a.run_allocation,
            basis=(ALLOCATION_RULE,),
        ),
        StageSpec(
            name=a.STAGE_CHAIN,
            title="扶養の連鎖の人の分の額を申告者に集める",
            reads=(a.V_CHAIN, a.V_CLAIMANT, a.R_DED1, a.R_SPEC1, a.R_DIS1, a.R_ISDEP, a.R_CHILD1),
            writes=(a.V_CH_DED, a.V_CH_SPEC, a.V_CH_DIS, a.V_CH_ANY, a.V_CH_CHILD, a.V_CH_SPEC_N),
            run=a.run_chain,
            basis=(CHAIN_RULE,),
        ),
    ),
    checks=(check_personal,),
    rules=RULES,
)

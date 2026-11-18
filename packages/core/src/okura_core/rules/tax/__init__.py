"""規則モジュール tax：所得控除の合計・課税所得・税額・精算・申告の要否・期限。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...registry import RecordKind, RoundingSlotSpec, RuleModule
from .basis import BASIS, RULES
from .checks import CHECKS
from .inputs import DECISIONS, build_inputs
from .refund import DECISION as REFUND_DECISION
from .refund import STAGE as REFUND_STAGE
from .variables import VARIABLES

MODULE = RuleModule(
    name="tax",
    title="税額と申告",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    # 使う記録の種類だけ（salary_payment は kyuyo も使う）。公的年金等・退職手当等の源泉徴収票は支払の記録と突き合わせる（支払の記録を使うのは income_kinds）。
    # 報酬の支払調書（payment_record）はここに書かない（収入の側の規則がなく、書くと所得の集め忘れの検出 scope.INCOME_RELATED_KINDS が働かなくなる）。
    record_kinds=frozenset(
        {
            "salary_payment",
            "prepayment_notice",
            "housing_loan_credit",
            "external_tax_credit",
            "heirship",
            "estate_liquidator",
            "tax_agent_notice",
            RecordKind("withholding_slip", "slip_type", frozenset({"public_pension", "retirement"})),
        }
    ),
    build_inputs=build_inputs,
    decisions=DECISIONS + (REFUND_DECISION,),
    # 2026-11-12：選択.還付申告（C-13）は還付申告ができる人だけ読む（読んだときだけ開く1か所。refund.py）
    stages=(REFUND_STAGE,),
    roundings=(
        RoundingSlotSpec(
            name="復興特別所得税額の1円未満",
            variable="所得税_復興特別所得税額の端数の候補",
            title="復興特別所得税額（基準所得税額×2.1%）の1円未満の端数（根拠を登録していない年分だけ候補で評価する）",
        ),
    ),
    checks=CHECKS,
    rules=RULES,
    basis=BASIS,
)

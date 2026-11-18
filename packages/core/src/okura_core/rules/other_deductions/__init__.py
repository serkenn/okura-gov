"""規則モジュール other_deductions：その他の所得控除と医療費の前処理。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...registry import RoundingSlotSpec, RuleModule
from .basis import RULES
from .casualty import STAGE as CASUALTY_STAGE
from .checks import CHECKS
from .inputs import DECISIONS, build_inputs
from .life_special import STAGE
from .variables import VARIABLES
from .filing import VARIABLES as FILING_VARIABLES

MODULE = RuleModule(
    name="other_deductions",
    title="その他の所得控除と医療費の前処理",
    directory=Path(__file__).resolve().parent,
    # 医療費控除の明細書の計算欄の途中の値（filing.py。2026-11-12）
    variables=VARIABLES + FILING_VARIABLES,
    record_kinds=frozenset(
        {
            "medical_payment",
            "medical_expense_notice",
            "reimbursement",
            "health_checkup_record",
            "social_insurance_payment",
            "mutual_aid_payment",
            "insurance_payment",
            "insurance_contract",
            "donation",
            "casualty",
            "casualty_expenditure",
        }
    ),
    build_inputs=build_inputs,
    decisions=DECISIONS,
    roundings=(
        RoundingSlotSpec(
            name="医療費控除の足切りの端数",
            variable="所得税_医療費控除の足切りの端数",
            title="総所得金額等の百分の五の1円未満の端数",
        ),
        RoundingSlotSpec(
            name="寄附金控除の上限の端数",
            variable="所得税_寄附金控除の上限の端数",
            title="総所得金額等の百分の四十の1円未満の端数",
        ),
        RoundingSlotSpec(
            name="医療費の補塡のあん分の端数",
            variable=None,
            title="補塡される部分の金額を支払った医療費の額に応じてあん分した額の1円未満の端数（質疑応答事例 05/61）",
        ),
        RoundingSlotSpec(
            name="保険料の前納・居住割合のあん分の端数",
            variable=None,
            title="前納した保険料の年分の額（所基通74・75−1(2)・76−3(3)・77−7）と居住割合による地震保険料の按分（77−5）の1円未満の端数",
        ),
        RoundingSlotSpec(
            name="雑損控除の足切りの端数",
            variable="所得税_雑損控除の足切りの端数",
            title="総所得金額等の10分の1の1円未満の端数（雑損控除）",
        ),
    ),
    stages=(STAGE, CASUALTY_STAGE),
    checks=CHECKS,
    rules=RULES,
)

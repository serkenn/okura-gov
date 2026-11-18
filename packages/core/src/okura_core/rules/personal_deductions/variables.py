"""規則モジュール personal_deductions の変数の一覧（facts.py・classify.py・judgments.py・deductions.py・filing.py）。"""

from __future__ import annotations

from .classify import CLASSIFY_VARIABLES
from .deductions import DEDUCTION_VARIABLES
from .facts import FACT_VARIABLES
from .filing import FILING_VARIABLES
from .judgments import JUDGMENT_VARIABLES

VARIABLES = FACT_VARIABLES + CLASSIFY_VARIABLES + JUDGMENT_VARIABLES + DEDUCTION_VARIABLES + FILING_VARIABLES

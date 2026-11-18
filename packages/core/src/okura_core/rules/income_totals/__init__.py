"""規則モジュール income_totals：所得の合計・損益通算・繰越控除・所得金額調整控除（中心の概念）。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...registry import RecordKind, RoundingSlotSpec, RuleModule
from .basis import RULES
from .checks import CHECKS
from .inputs import DECISIONS, RETURN_TYPES, build_inputs
from .variables import VARIABLES
from .jumin import VARIABLES as JUMIN_VARIABLES
from .filing import VARIABLES as FILING_VARIABLES
from .uncollectible import VARIABLES as UNCOLLECTIBLE_VARIABLES
from .tokutei import VARIABLES as TOKUTEI_VARIABLES  # 地方税法第313条第11項の前年の所得の窓口（juminzei JM-42。2026-11-12 の3回目）

MODULE = RuleModule(
    name="income_totals",
    title="所得の合計・損益通算・繰越・繰戻し",
    directory=Path(__file__).resolve().parent,
    # 住民税への窓口（jumin.py。JM-19・20・23）、kyuyo への窓口（uncollectible.py。所令180②一：KY-08）、申告書の欄の途中の値（filing.py。2026-11-12）
    variables=VARIABLES + JUMIN_VARIABLES + UNCOLLECTIBLE_VARIABLES + FILING_VARIABLES + TOKUTEI_VARIABLES,
    record_kinds=frozenset({RecordKind("filed_document", "document_type", RETURN_TYPES)}),
    build_inputs=build_inputs,
    decisions=DECISIONS,
    roundings=(
        RoundingSlotSpec(
            name="一時所得の2分の1",
            variable="所得税_一時所得の2分の1の端数の候補",
            title="総所得金額に入れる一時所得の金額の2分の1の1円未満の端数（令和7年分は手引きの切捨て、令和8年分は根拠が見つからず候補で評価）",
        ),
    ),
    checks=CHECKS,
    rules=RULES,
)

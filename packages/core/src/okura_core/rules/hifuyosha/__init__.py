"""規則モジュール hifuyosha：健康保険・共済組合（国家公務員・地方公務員・私学）の被扶養者の判定（判定日ごと）。README.md を見る。"""

from __future__ import annotations

from pathlib import Path

from ...registry import RoundingSlotSpec, RuleModule
from .basis import RULES
from .inputs import DECISIONS, INJECTIONS, RECORD_KINDS, ROUNDING_CONTRACT, build_groups, build_inputs
from .variables import VARIABLES

MODULE = RuleModule(
    name="hifuyosha",
    title="健康保険・共済組合の被扶養者",
    directory=Path(__file__).resolve().parent,
    variables=VARIABLES,
    record_kinds=RECORD_KINDS,
    build_inputs=build_inputs,
    decisions=DECISIONS,
    injections=INJECTIONS,
    roundings=(
        RoundingSlotSpec(
            name=ROUNDING_CONTRACT,
            variable=None,
            title="労働契約の時給×所定労働時間などから見込んだ年間収入の1円未満の端数（通知・Q&A に定めがない）",
        ),
    ),
    groups={"健康保険一覧": build_groups},
    rules=RULES,
)

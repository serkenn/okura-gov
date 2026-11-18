"""規則モジュール income_kinds：所得の種類ごとの所得（給与所得は kyuyo）。README.md を見る。

実装したもの：公的年金等・年金の種類ごとの雑所得、一時所得、退職所得、事業所得・業務に係る雑所得・不動産所得
（家内労働者等の特例・青色申告特別控除・専従者・減価償却・消費税等の経理方式を含む）、雑所得の合計、青色申告の承認、配当・株式等。
"""

from __future__ import annotations

from pathlib import Path

from ...registry import DecisionSpec, ModuleInputs, RoundingSlotSpec, RuleModule, YearContext
from .assets import ROUNDING_EXPENSE
from .basis import RULES
from .checks import CHECKS
from .inputs import DECISIONS, RECORD_KINDS, V_ROUNDING, build_inputs
from .variables import VARIABLES
from .jumin import VARIABLES as JUMIN_VARIABLES
from .filing import VARIABLES as FILING_VARIABLES
from .breakdown import VARIABLES as BREAKDOWN_VARIABLES
from .uncollectible import VARIABLES as UNCOLLECTIBLE_VARIABLES
from .forms_items import VARIABLES as FORMS_ITEM_VARIABLES
from .asset_rows import VARIABLES as ASSET_ROW_VARIABLES
from .prior_years import VARIABLES as PRIOR_YEAR_VARIABLES  # 前々年分の業務に係る雑所得の収入金額・所法120⑥（IK-114）
from .form_override import K_FORM_MAP, write_form_overrides
from .form_override import VARIABLES as FORM_OVERRIDE_VARIABLES
from .tokutei import VARIABLES as TOKUTEI_VARIABLES  # 地方税法第313条第11項の前年の所得の窓口（juminzei JM-42。2026-11-12 の3回目）


def _build_inputs(ctx: YearContext) -> ModuleInputs:
    """inputs.build_inputs に、科目の割当ての選択（form_override.py。選択.様式への割当て C-18）を足す。"""
    out = build_inputs(ctx)
    write_form_overrides(ctx, out)
    return out

#: 根拠のない端数（D21 R5・D22 S3）：退職所得の金額（残額の2分の1）の1円未満。所得の金額の側を候補で丸める。
ROUNDING = RoundingSlotSpec(
    name="所得の金額の1円未満（退職所得）",
    variable=V_ROUNDING,
    title="退職所得の金額の1円未満の端数（所法30② に定めがない）",
)
#: 根拠のない端数：按分の後の必要経費・一括償却の3分の1・事業専従者控除の除算・配当の負債の利子の月割の1円未満（genka-hasu H2、fudosan §9-3）。
ROUNDING_EXP = RoundingSlotSpec(
    name=ROUNDING_EXPENSE,
    variable=None,
    title="必要経費の1円未満の端数（按分・一括償却の3分の1・事業専従者控除の除算・配当の負債の利子の月割に定めがない）",
)

MODULE = RuleModule(
    name="income_kinds",
    title="所得の種類ごとの所得",
    directory=Path(__file__).resolve().parent,
    # 住民税への窓口（jumin.py。JM-23）、kyuyo への窓口（uncollectible.py。所令180②一：KY-08）、申告書の欄の途中の値（filing.py。2026-11-12）、
    # 総収入金額・必要経費の内訳と事業専従者の事業主（breakdown.py。様式の科目 UO19・行の割当て UO23。2026-11-12）、
    # 減価償却費の計算の資産ごとの行（asset_rows.py。2026-11-12）、科目の割当ての選択（form_override.py。2026-11-12）
    variables=VARIABLES + JUMIN_VARIABLES + UNCOLLECTIBLE_VARIABLES + FILING_VARIABLES + BREAKDOWN_VARIABLES + FORMS_ITEM_VARIABLES + ASSET_ROW_VARIABLES
    + FORM_OVERRIDE_VARIABLES + PRIOR_YEAR_VARIABLES + TOKUTEI_VARIABLES,
    record_kinds=RECORD_KINDS,
    build_inputs=_build_inputs,
    # 選択.様式への割当て：入力があるときだけ読む（科目の割当ては税額を変えないので候補で評価しない：form_override.py）
    decisions=DECISIONS + (DecisionSpec(kind=K_FORM_MAP, slots=lambda ctx: ()),),
    roundings=(ROUNDING, ROUNDING_EXP),
    rules={
        **RULES,
        "所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額": RULES["所得税_公的年金等控除額"],
        "所得税_回収不能額等の前の公的年金等に係る雑所得の金額": RULES["所得税_公的年金等控除額"],
    },
    checks=CHECKS,
)

"""規則モジュールの登録の一覧（packages/core/README.md §10）。

モジュールを足すときは、rules/<名前>/__init__.py に MODULE（registry.RuleModule）を書き、下に1行
`from .<名前> import MODULE as <名前>` を足す。ほかの共有のファイルは触らない。
並びは評価の順に効かない（変数の依存の順は概念辞書から決まる）が、結果を決定的にするため、この並びを使う。
"""

from __future__ import annotations

from ..registry import RuleModule

from .kyuyo import MODULE as kyuyo  # noqa: E402  給与所得
from .income_totals import MODULE as income_totals  # noqa: E402  所得の合計（合計所得金額の暫定の式）
from .personal_deductions import MODULE as personal_deductions  # noqa: E402  人的控除と扶養（扶養親族の所得要件）
from .income_kinds import MODULE as income_kinds  # noqa: E402  所得の種類ごとの所得（公的年金等・一時・退職・事業・業務）
from .other_deductions import MODULE as other_deductions  # noqa: E402  その他の所得控除と医療費の前処理
from .tax import MODULE as tax  # noqa: E402  税額と申告（所得控除の合計・課税所得・税額・精算・申告の要否・期限）
from .juminzei import MODULE as juminzei  # noqa: E402  住民税（市町村民税・道府県民税）と森林環境税
from .hifuyosha import MODULE as hifuyosha  # noqa: E402  健康保険・共済組合の被扶養者
from .kokuho import MODULE as kokuho  # noqa: E402  国民健康保険料（税）の法令の構造
from .kokunen import MODULE as kokunen  # noqa: E402  国民年金（保険料・免除等の所得基準・第3号被保険者）

#: 登録した規則モジュール（上の import の順）。
MODULES: tuple[RuleModule, ...] = tuple(v for v in list(globals().values()) if isinstance(v, RuleModule))

__all__ = ["MODULES"]

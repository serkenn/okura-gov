"""規則モジュール other_deductions の計算の後の対象外の検出（黙って近似しない）。

今はない。雑損控除の親族の資産の所属（所令第205条第2項）は、以前ここで対象外にしていたが、段階評価の段（casualty.STAGE）で
扶養の割当ての結果を読んで決めるようにした（2026-11-11。HANDOFF D24③）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ...registry import CheckContext, Exclusion

CHECKS: tuple[Callable[[CheckContext], Iterable[Exclusion]], ...] = ()

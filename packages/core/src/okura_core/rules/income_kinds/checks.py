"""規則モジュール income_kinds の計算の後の対象外の検出（RuleModule.checks）。

いまは検出がない。以前の `check_home_worker_loss`（家内労働者等の特例で事業所得が赤字になる人を対象外にする検出）は、2026-11-12 に
D22 S1 で国税庁の計算書の読みで計算することにして外した（calc.home_worker_expenses・basis.HOME_WORKER_DEFICIT。README の IK-100）。
"""

from __future__ import annotations

CHECKS: tuple = ()

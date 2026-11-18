"""中間表現から判定の時の事実を取り出す道具は、共有の場所 okura_core/dependents/ir_facts.py に移した（2026-11-12。juminzei JM-24〜26）。

このファイルは、このモジュールのほかのファイル・テストが使う名前を写すだけ。
"""

from __future__ import annotations

from ...dependents.ir_facts import *  # noqa: F401,F403
from ...dependents.ir_facts import FOREIGN, J_ADDRESS_KIND  # noqa: F401

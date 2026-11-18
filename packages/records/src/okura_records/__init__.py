"""okura_records：記録層（beancount の安全な読み込み、アダプタ、事実台帳・判断台帳、中間表現の作成）。

okura_ir と beancount に依存する。判定コア（okura_core）とは互いに import しない（SCOPE §6）。

モジュール（import するとき beancount を読み込むのは safe_loader と adapter だけ）：
  safe_loader       load_ledger(main, root=None) -> LoadResult           台帳を安全に読む
  adapter           normalize(ledger) -> (取引 JSON, 問題)              台帳 → 正規化した取引 JSON
  facts_ledger      read(bytes, source) -> (LedgerState, 問題)          事実台帳（追記のみの JSON Lines）
  judgments_ledger  read(bytes, source) -> (LedgerState, 問題)          判断台帳（追記のみの JSON Lines）
  ledger_map        PLACEMENTS・guide_markdown()                       語彙の種類ごとの書く場所（台帳の取引・事実台帳・判断台帳）
  build_ir          build_ir(取引 JSON, 事実の状態, 判断の状態) -> BuildResult   中間表現を作る（純粋関数）
  cli               python -I -X utf8 -m okura_records.cli build-ir --ledger … --facts … --judgments …
"""

from .problem import Problem

__all__ = ["Problem"]

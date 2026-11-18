"""okura_ir：中間表現の約束（JSON Schema）と、それを解釈する自作の検査器（標準ライブラリだけ）。

判定コア（okura_core）と記録層（okura_records）の両方が使う。どちらにも依存しない。

公開するもの：
  SCHEMA_VERSION         中間表現の版（"0"）
  Problem                検査の問題（path・code・message）
  validate(ir)           中間表現を検査して Problem の一覧を返す（例外を送出しない）
  loads(data)            JSON を厳密に読む（重複キー・NaN・BOM などを拒否）。(値, 問題の一覧)
  load_schema()          同梱の ir.schema.json（dict）
"""

from .jsonio import loads
from .problem import Problem
from .validate import load_schema, validate
from .vocabulary import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "Problem", "load_schema", "loads", "validate"]

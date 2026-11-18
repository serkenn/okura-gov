"""様式の欄の対応表（SCOPE §3、HANDOFF D19 T5-2）：年分ごとの欄 → 概念の対応のデータと、結果から欄ごとの値を作る純粋関数。

判定コア（evaluate）は様式を知らない。この部品は判定コアの結果の値を受け取り、計算をせずに欄へ写す（SCOPE §6-1）。
ファイル（e-Tax の XML・PDF・Excel）を作るのは利用アプリ（SCOPE §4）。使い方は README.md。
"""

from .fill import (
    FieldStatus,
    FieldValue,
    FilingType,
    FormOutput,
    FormsRefusal,
    FormsResult,
    RefusalCategory,
    determine_filing_type,
    fill_forms,
)
from .table import (
    FILING_TYPES,
    FieldSpec,
    FormTable,
    FormTableError,
    YearTables,
    check_against_dictionary,
    load_index,
    load_year,
    parse_form,
)

__all__ = [
    "FILING_TYPES",
    "FieldSpec",
    "FieldStatus",
    "FieldValue",
    "FilingType",
    "FormOutput",
    "FormTable",
    "FormTableError",
    "FormsRefusal",
    "FormsResult",
    "RefusalCategory",
    "YearTables",
    "check_against_dictionary",
    "determine_filing_type",
    "fill_forms",
    "load_index",
    "load_year",
    "parse_form",
]

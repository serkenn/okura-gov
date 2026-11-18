"""規則モジュール income_kinds：減価償却費の計算の資産ごとの行（2026-11-12。様式の対応表 forms の収支内訳書（一般用）2ページ・
青色申告決算書（一般用）3ページの「減価償却費の計算」の償却の列）。

判定コアの結果は「概念 × 人 × 時点」なので、資産ごとの値は「行 k の資産」の概念（人・年の概念を行の番号ごとに）として出す
（breakdown.py の内訳のキーごとの変数と同じく、変数を機械的に作る）。

- 行に載せる資産：事業所得の側（biz）の資産で、その年分に償却費（少額・一括・措法28の2 を含む：減価償却費に入る額）を計算したもの
  （減価償却費の合計 `所得税.事業所得の減価償却費` に入る資産と同じ。償却の終わった資産もその年に持っていれば 0 の行）。
  業務に係る雑所得・不動産所得の資産は載せない（決算書・収支内訳書の一般用は事業所得。業務に係る雑所得の収支内訳書は作らない）。
- 並べ方：様式に定めがないので既定の並べ方（取得の日の早い順、同じなら資産の ID 順）。表示だけで税額は変わらない
  （forms/README の行の割当て〔design-output UO23〕と同じ扱い）。行の数（ROWS＝決算書の7）を超える資産は行に載せない（あふれ：適宜の用紙）。
  資産の数（`所得税.事業所得の減価償却資産の数`）で、様式の行の数を超えるかが分かる。
- 列の値（assets.py の asset_year・_book_year・depreciation_schedule から）：償却の基礎になる金額（その年の式の基礎：定額法は取得価額、旧定額法は
  取得価額−残存価額、定率法・旧定率法は期首未償却残高、定率法で改定償却率に切り替えた年からは改定取得価額、所令134② の年は取得価額−95%相当額−1円。
  1円未満は切上げ：calc.DEPRECIATION_CEIL）、償却方法、耐用年数、償却率（定率法で改定償却率に切り替えた年は改定償却率、所令134② の年は 1/5）、
  本年中の償却期間（所令132 の月数：取得の年・処分の年はその月数、ほかは12）、普通償却費（事業専用割合を掛ける前）、割増（特別）償却費
  （外部の値：special_dep.py。2026-11-12）、償却費合計（＝普通償却費＋割増（特別）償却費）、事業専用割合、必要経費算入額（償却費合計×事業専用割合）、
  未償却残高（期末。償却費の全額で減らす：案A）、
  償却保証額（定率法だけ。決算書のイ欄のカッコ）。
  少額（所令138）・一括（所令139）・措法28の2・特別な方法（生産高比例法・リース期間定額法など：assets_special.py）は、耐用年数・償却率・
  本年中の償却期間・償却の基礎（特別な方法）を 0／「なし」にする（様式の欄は空欄。式 ロ×ハ×ニ の形でない）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from fractions import Fraction

from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...registry import ModuleInputs
from ...result import OutOfScopeReason, Split, State

GENKA = "docs/public-sources/20261109_round2_genka-laws-and-nta.md"
GENKA3 = "docs/public-sources/20261111_impl-research3_genka-laws.md"
AOIRO = "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md"
YOSHIKI = "docs/public-sources/20261109_round2_yoshiki-forms-r07.md"

#: 行の数（青色申告決算書（一般用）3ページの7行。収支内訳書（一般用）2ページは6行で、7行目の資産はその様式ではあふれ）。
ROWS = 7
#: 行に資産がないとき（結果の区分の値は空でない文字列：result.Category）。
NO_ASSET = "なし"
#: 率がない（少額・一括の全額・特別な方法）。
NO_RATE = "なし"

#: 変数名の制度の接頭辞（「所得税」＋「_」。文字列の定数を変数名と取り違えないよう分けて書く：tests/test_architecture の名前の検査）。
_PREFIX = "所得税"

#: 列（概念・変数の名前の末尾, 値の型）。
COLUMNS: tuple[tuple[str, type], ...] = (
    ("資産のID", str),
    ("償却の基礎になる金額", int),
    ("償却方法", str),
    ("耐用年数", int),
    ("償却率", str),
    ("本年中の償却期間", int),
    ("本年分の普通償却費", int),
    ("本年分の割増償却費", int),
    ("本年分の償却費合計", int),
    ("事業専用割合", str),
    ("本年分の必要経費算入額", int),
    ("未償却残高", int),
    ("償却保証額", int),
)
_STR_DEFAULTS = {"資産のID": NO_ASSET, "償却方法": NO_RATE, "償却率": NO_RATE, "事業専用割合": NO_RATE}


def row_variable(k: int, column: str) -> str:
    """行 k（1 から）の列の変数名（概念 ID は 所得税.事業所得の減価償却資産の行<k>.<列>）。"""
    return f"{_PREFIX}_事業所得の減価償却資産の行{k}_{column}"


V_COUNT = f"{_PREFIX}_事業所得の減価償却資産の数"


def all_variables() -> tuple[str, ...]:
    return tuple(row_variable(k, c) for k in range(1, ROWS + 1) for c, _ in COLUMNS) + (V_COUNT,)


@dataclass(frozen=True)
class AssetRow:
    """資産1つのその年分の行（assets.AssetResult.rows）。金額は整数の円。"""

    asset_id: str
    side: str
    acquired: _dt.date
    method: str  # 償却方法の名前
    base: int  # 償却の基礎になる金額（0 は空欄）
    years: int  # 耐用年数（0 は空欄）
    rate: Fraction | None  # 償却率（None は空欄）
    months: int  # 本年中の償却期間（0 は空欄）
    ordinary: int  # 本年分の普通償却費（事業専用割合を掛ける前）
    share: Fraction | None  # 事業専用割合（None は全部）
    expense: int  # 本年分の必要経費算入額
    unamortized: int  # 未償却残高（期末）
    guarantee: int = 0  # 償却保証額（定率法だけ）
    special: int = 0  # 本年分の割増（特別）償却費（外部の値：special_dep.py。事業専用割合を掛ける前。2026-11-12）
    ids: tuple[str, ...] = ()
    states: frozenset[State] = field(default_factory=frozenset)


def rate_text(rate: Fraction | None) -> str:
    """償却率の文字列：千分率で書ける率は小数3桁（0.200）、ほかは分数（1/3）。なければ「なし」。"""
    if rate is None:
        return NO_RATE
    milli = rate * 1000
    if milli.denominator == 1:
        n = int(milli)
        return f"{n // 1000}.{n % 1000:03d}"
    return f"{rate.numerator}/{rate.denominator}"


def share_text(share: Fraction | None) -> str:
    """事業専用割合の文字列：百分率で整数なら 60%、ほかは分数（1/3）。割合の判断がなければ 100%。"""
    if share is None:
        return "100%"
    pct = share * 100
    if pct.denominator == 1:
        return f"{int(pct)}%"
    return f"{share.numerator}/{share.denominator}"


def ordered(rows: Iterable[AssetRow]) -> list[AssetRow]:
    """行の並べ方（様式に定めがない：既定の並べ方）：取得の日の早い順、同じなら資産の ID 順。"""
    return sorted(rows, key=lambda r: (r.acquired, r.asset_id))


def row_values(row: AssetRow | None) -> dict[str, object]:
    """行の列 → 値（資産がなければ既定値）。"""
    if row is None:
        return {c: (_STR_DEFAULTS[c] if t is str else 0) for c, t in COLUMNS}
    return {
        "資産のID": row.asset_id,
        "償却の基礎になる金額": row.base,
        "償却方法": row.method,
        "耐用年数": row.years,
        "償却率": rate_text(row.rate),
        "本年中の償却期間": row.months,
        "本年分の普通償却費": row.ordinary,
        "本年分の割増償却費": row.special,
        "本年分の償却費合計": row.ordinary + row.special,
        "事業専用割合": share_text(row.share),
        "本年分の必要経費算入額": row.expense,
        "未償却残高": row.unamortized,
        "償却保証額": row.guarantee,
    }


def write_rows(
    out: ModuleInputs,
    pid: str,
    rows: Iterable[AssetRow],
    missing: Iterable[Split],
    reasons: Iterable[OutOfScopeReason],
) -> None:
    """事業所得の側の行を書く。reasons があれば（資産の償却を決められない資産がある）行の全部と資産の数を対象外にする。"""
    rows = ordered(r for r in rows if r.side == "biz")
    missing, reasons = tuple(missing), tuple(reasons)
    all_ids = tuple(sorted({i for r in rows for i in r.ids}))
    all_states: set[State] = set()
    for r in rows:
        all_states |= set(r.states)
    for reason in reasons:
        for v in all_variables():
            out.exclude(pid, reason, v)
    for k in range(1, ROWS + 1):
        row = rows[k - 1] if k <= len(rows) and not reasons else None
        ids, states = (row.ids, set(row.states)) if row is not None else (all_ids, all_states)
        for column, value in row_values(row).items():
            out.set(row_variable(k, column), pid, value, ids, states, missing=missing)
    out.set(V_COUNT, pid, 0 if reasons else len(rows), all_ids, all_states, missing=missing)


def _variable(name: str, label: str, vt: type) -> type:
    attrs: dict[str, object] = {
        "value_type": vt, "entity": 人物, "definition_period": YEAR, "label": label,
        "reference": [f"{GENKA}#2.3", f"{GENKA}#4", f"{GENKA3}#2", f"{AOIRO}#7.3", f"{YOSHIKI}#6.3"], "__module__": __name__,
    }  # fmt: skip
    if vt is str:
        attrs["default_value"] = _STR_DEFAULTS[name.rsplit("_", 1)[-1]]
    return type(name, (Variable,), attrs)


_VARS: list[type] = [
    _variable(row_variable(k, c), f"減価償却費の計算の行{k}の資産の{c}（事業所得。行に資産がなければ既定値）", t)
    for k in range(1, ROWS + 1)
    for c, t in COLUMNS
]
_VARS.append(_variable(V_COUNT, "減価償却費の計算に載せる事業所得の資産の数（行の数を超える資産はあふれ：適宜の用紙）", int))

VARIABLES: tuple[type, ...] = tuple(_VARS)

__all__ = [
    "COLUMNS",
    "NO_ASSET",
    "NO_RATE",
    "ROWS",
    "V_COUNT",
    "VARIABLES",
    "AssetRow",
    "all_variables",
    "ordered",
    "rate_text",
    "row_values",
    "row_variable",
    "share_text",
    "write_rows",
]

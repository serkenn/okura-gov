"""住民税への窓口（2026-11-12 の3回目。rules/juminzei/README.md JM-42）：特定支出控除を当てた場合の前年の所得（地方税法第313条第11項・第32条第11項）。

前年分の所得税の納税義務がない人が住民税の申告書だけで受ける特定支出控除は、「所得税法第五十七条の二第一項の規定の例により」給与所得の計算上控除し、
前年の所得は「所得税の計算の例」（第313条第2項）で計算する（docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md §6、仮説 impl-research8 H10）。
所得税の値と違うのは給与所得の金額から始まる次の連鎖なので、所得税と同じ関数（損益通算・一時所得の2分の1・繰越控除・所得金額調整控除の第2項・公的年金等控除額）を、
給与所得を kyuyo の 所得税_特定支出控除を当てた場合の給与所得の金額 にして当て直す：

1. 未払の給与の回収不能額等（所法64①・所令180②）：一号の「直前に確定している」総所得金額・退職所得金額の合計額（この版の
   所得税_特定支出控除を当てた場合の回収不能額等の前の総所得金額と退職所得金額の合計額）と、二号の差額（kyuyo の
   所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額）のいずれか低い金額を給与所得の金額から引く。
   所得金額調整控除の第1項は所得税の値（扶養の判定の段の後の確定した値）をそのまま使う（第1項は給与等の収入金額と「有するか」だけで決まり、特定支出控除で変わらない）。
   所得税の側（rules/kyuyo/uncollectible.py）のような段は要らない：この値は所得税の扶養の判定に戻らない（住民税だけが読む）ので循環しない。
2. 公的年金等控除額の区分（所法35④ の公的年金等に係る雑所得以外の合計所得金額）：特定支出控除・回収不能額等の後の給与所得で求め直す（income_kinds の
   所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額。分離課税に係る退職所得のある人は退職所得を除いた区分：JM-23 と同じ）。
3. 所得金額調整控除の第2項：公的年金等に係る雑所得の金額が変わる分だけ計算し直す（給与の側は特定支出控除の前の給与所得控除後の給与等の金額：仮説 impl-research8 H6）。
4. 損益通算（所令198）・一時所得の2分の1（令和7年分は手引きの切捨て、令和8年分は所得税と同じ候補 所得税_一時所得の2分の1の端数の候補）。

当たらない人（特定支出の額の合計額が給与所得控除額の2分の1 を超えない人）は0（juminzei の段はその人の値を読まない。行を0にするので一時所得の端数の候補も引かない）。
2分の1 を超える人がいない評価では計算しない。式は依存を静的に読めるように変数を式の中で引き、行の組み立てだけを関数にする（tests/test_architecture.py）。
以前（2026-11-12 の2回目）は juminzei の段が所得税の合計所得金額との差で計算し、回収不能額等のある人・公的年金等控除額の区分が変わりうる人を c-限界 の対象外にしていた（JM-42）。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import AfterOffset, adjustment_2, half_ichiji, listed
from .jumin import _jumin_rows
from .uncollectible import _pre_totals
from .variables import _half_candidates_needed, _half_rounders, _ints, _offsets, _out, _rules2

_PS8 = "docs/public-sources/20261112_impl-research8_tokutei-shishutsu-laws.md"
_SHOTOKU4 = "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md"
_NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#2.1"
_TAISHOKU = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#6.3"
_GENKA = "docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.1"


def _zeros(a: object) -> np.ndarray:
    return np.zeros(len(a), dtype=np.int32)  # type: ignore[arg-type]


def _masked(values: Sequence[object], mask: object) -> list[tuple[int, ...]]:
    """配列の並び → 人ごとの整数の行。当たらない人の行は0にする（その人の一時所得の端数の候補を引かない）。"""
    return [row if bool(m) else tuple(0 for _ in row) for row, m in zip(_ints(*values), mask)]  # type: ignore[call-overload, arg-type]


def _excl_after(rows: list[tuple[int, ...]], retirement: bool) -> list[AfterOffset]:
    """公的年金等に係る雑所得以外の合計所得金額（所法35④）の損益通算。rows：配当・不動産・事業・給与・業務雑・その他雑・一時・退職・上場配当・上場譲渡・通算。
    retirement が偽なら退職所得を除く（住民税の分離課税に係る退職所得のある人の区分：JM-23）。"""
    return _offsets([(a, b, c, d, e1 + e2, f, g if retirement else 0) for a, b, c, d, e1, e2, f, g, *_ in rows])


def _excl_total(rows: list[tuple[int, ...]], after: list[AfterOffset], rounders: list, retirement: bool) -> np.ndarray:
    out = []
    for x, r, row in zip(after, rounders, rows):
        ls = listed(row[8], row[9], 0, offset=bool(row[10]), carry=False)
        out.append(x.keijo + half_ichiji(x.ichiji, r) + (x.taishoku if retirement else 0) + ls.dividend_offset + ls.gain)
    return _out(out)


def _tokutei_rows(values: Sequence[object], mask: object, rules: object) -> tuple[list[tuple[int, ...]], list[AfterOffset]]:
    """values：配当・不動産・事業・給与（特定支出控除・回収不能額等の後）・雑・公的年金等の雑（所得税）・公的年金等の雑（特定支出控除を当てた区分）・一時・退職・
    上場配当・上場譲渡・通算・所得金額調整控除（所得税）・給与所得控除後の給与等の金額。雑所得の公的年金等の部分を置き換え、所得金額調整控除の第2項を計算し直した行
    （配当・不動産・事業・給与〔調整控除の後〕・雑・一時・退職・上場配当・上場譲渡・通算）と損益通算の結果。"""
    rows = []
    for a, b, c, d, e, nk, nt, f, g, ld, lg, o, adj, w in _masked(values, mask):
        adj_t = adj - adjustment_2(w, nk, rules) + adjustment_2(w, nt, rules) if nt != nk else adj  # type: ignore[arg-type]
        rows.append((a, b, c, d - adj_t, e - nk + nt, f, g, ld, lg, o))
    return rows, _offsets([r[:7] for r in rows])


def _total(rows: list[tuple[int, ...]], after: list[AfterOffset], rounders: list) -> np.ndarray:
    out = []
    for x, r, row in zip(after, rounders, rows):
        ls = listed(row[7], row[8], 0, offset=bool(row[9]), carry=False)
        out.append(x.keijo + half_ichiji(x.ichiji, r) + x.taishoku + ls.dividend_offset + ls.gain)
    return _out(out)


class 所得税_特定支出控除を当てた場合の回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "給与所得を特定支出控除を当てた場合の所得税法第64条第1項の前の額にして計算した公的年金等に係る雑所得以外の合計所得金額"
        "（地方税法第313条第11項の前年の所得の所令180②一の公的年金等控除額の区分。回収不能額等と2分の1を超える特定支出のある人だけ。JM-42）"
    )
    reference = [_NENKIN, f"{_SHOTOKU4}#1.1", f"{_PS8}#6"]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        mask = over & (回収不能 > 0)
        if not np.any(mask):
            return _zeros(over)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の給与所得の金額", period), 人("所得税_業務に係る雑所得の金額", period),
            人("所得税_その他の雑所得の金額", period), 人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period),
            人("所得税_上場株式等に係る配当所得等の金額", period), 人("所得税_上場株式等に係る譲渡所得等の金額", period),
            人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
        ]  # fmt: skip
        rows = _masked(values, mask)
        after = _excl_after(rows, True)
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _excl_total(rows, after, _half_rounders(period, 候補, len(rows)), True)


class 所得税_特定支出控除を当てた場合の回収不能額等の前の総所得金額と退職所得金額の合計額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除を当てた場合の所得税法施行令第180条第2項第1号の合計額（回収不能額等が生じた時の直前において確定している総所得金額と退職所得金額。"
        "損益通算・繰越控除の後。所得金額調整控除の第1項は所得税の値。地方税法第313条第11項の前年の所得：JM-42）"
    )
    reference = [f"{_SHOTOKU4}#1.1", f"{_SHOTOKU4}#1.3", f"{_PS8}#6"]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        mask = over & (回収不能 > 0)
        if not np.any(mask):
            return _zeros(over)
        rules = _rules2(parameters(period).所得税.所得金額調整控除.第2項)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の給与所得の金額", period), 人("所得税_業務に係る雑所得の金額", period),
            人("所得税_その他の雑所得の金額", period), 人("所得税_特定支出控除を当てた場合の回収不能額等の前の公的年金等に係る雑所得の金額", period),
            人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の繰越控除額", period),
            人("所得税_繰り越された純損失の金額", period), 人("所得税_繰り越された雑損失の金額", period),
            人("所得税_所得金額調整控除", period), 人("所得税_公的年金等に係る雑所得の金額", period), 人("所得税_給与所得控除後の給与等の金額", period),
            人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
        ]  # fmt: skip
        rows = _masked(values, mask)
        # 所得金額調整控除：第1項は所得税の値のまま、第2項は公的年金等に係る雑所得の金額（回収不能額等の前の区分）で計算し直す
        adj = [r[14] - adjustment_2(r[16], r[15], rules) + adjustment_2(r[16], r[6], rules) for r in rows]
        after = _offsets([(a, b, c, d - j, e1 + e2 + n, f, g) for (a, b, c, d, e1, e2, n, f, g, *_), j in zip(rows, adj)])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _pre_totals(rows, after, _half_rounders(period, 候補, len(rows)), [r[17] for r in rows])


class 所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除（所得税法第57条の2第1項）と未払の給与の回収不能額等（第64条第1項・施行令第180条第2項）を当てた給与所得の金額（所得金額調整控除の前）。"
        "地方税法第313条第11項の前年の給与所得（JM-42）。2分の1を超える特定支出のない人は0"
    )
    reference = [f"{_PS8}#1", f"{_PS8}#6", f"{_SHOTOKU4}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        if not np.any(over):
            return _zeros(over)
        g = 人("所得税_特定支出控除を当てた場合の給与所得の金額", period)
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        if not np.any(over & (回収不能 > 0)):
            return np.where(over, g, 0).astype(np.int32)
        差額 = 人("所得税_特定支出控除を当てた場合の回収不能額等に係る給与所得の金額の差額", period)
        上限 = 人("所得税_特定支出控除を当てた場合の回収不能額等の前の総所得金額と退職所得金額の合計額", period)
        out = [
            (int(x) - (min(int(d), int(c)) if u > 0 else 0)) if o else 0
            for x, d, c, u, o in zip(g, 差額, 上限, 回収不能, over)
        ]  # fmt: skip
        return _out(out)


class 所得税_特定支出控除を当てた場合の公的年金等に係る雑所得以外の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定支出控除を当てた場合の公的年金等に係る雑所得以外の合計所得金額（所得税法第35条第4項の区分の基。地方税法第313条第11項の前年の所得：JM-42）"
    reference = [_NENKIN, f"{_PS8}#6"]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        収入 = 人("所得税_公的年金等の収入金額", period)
        mask = over & (収入 > 0)
        if not np.any(mask):
            return _zeros(over)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額", period), 人("所得税_業務に係る雑所得の金額", period),
            人("所得税_その他の雑所得の金額", period), 人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period),
            人("所得税_上場株式等に係る配当所得等の金額", period), 人("所得税_上場株式等に係る譲渡所得等の金額", period),
            人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
        ]  # fmt: skip
        rows = _masked(values, mask)
        after = _excl_after(rows, True)
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _excl_total(rows, after, _half_rounders(period, 候補, len(rows)), True)


class 所得税_特定支出控除を当てた場合の退職所得を除いた公的年金等に係る雑所得以外の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除を当てた場合の、退職所得がないものとして計算した公的年金等に係る雑所得以外の合計所得金額（住民税の分離課税に係る退職所得のある人の"
        "公的年金等控除額の区分：JM-23・JM-42）"
    )
    reference = [_NENKIN, _TAISHOKU, f"{_PS8}#6"]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        収入 = 人("所得税_公的年金等の収入金額", period)
        mask = over & (収入 > 0)
        if not np.any(mask):
            return _zeros(over)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額", period), 人("所得税_業務に係る雑所得の金額", period),
            人("所得税_その他の雑所得の金額", period), 人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period),
            人("所得税_上場株式等に係る配当所得等の金額", period), 人("所得税_上場株式等に係る譲渡所得等の金額", period),
            人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
        ]  # fmt: skip
        rows = _masked(values, mask)
        after = _excl_after(rows, False)
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _excl_total(rows, after, _half_rounders(period, 候補, len(rows)), False)


class 所得税_特定支出控除を当てた場合の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除を当てた場合の合計所得金額（損益通算の後・繰越控除の前。所得税法第2条第1項第30号イ(2) の計算の例。"
        "地方税法第313条第11項の前年の所得：JM-42。2分の1を超える特定支出のない人は0）"
    )
    reference = [f"{_PS8}#6", _GENKA]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        if not np.any(over):
            return _zeros(over)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額", period), 人("所得税_雑所得の金額", period),
            人("所得税_公的年金等に係る雑所得の金額", period), 人("所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額", period),
            人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period),
            人("所得税_上場株式等に係る配当所得等の金額", period), 人("所得税_上場株式等に係る譲渡所得等の金額", period),
            人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period), 人("所得税_所得金額調整控除", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]  # fmt: skip
        rows, after = _tokutei_rows(values, over, _rules2(parameters(period).所得税.所得金額調整控除.第2項))
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _total(rows, after, _half_rounders(period, 候補, len(rows)))


class 所得税_特定支出控除を当てた場合の損益通算の後の退職所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定支出控除を当てた場合の損益通算の後・繰越控除の前の退職所得の金額（地方税法第313条第11項の前年の所得：JM-42。2分の1を超える特定支出のない人は0）"
    reference = [f"{_PS8}#6", _GENKA, _TAISHOKU]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        退職 = 人("所得税_退職所得の金額", period)
        if not np.any(over & (退職 != 0)):
            return _zeros(over)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額", period), 人("所得税_雑所得の金額", period),
            人("所得税_公的年金等に係る雑所得の金額", period), 人("所得税_特定支出控除を当てた場合の公的年金等に係る雑所得の金額", period),
            人("所得税_一時所得の金額", period), 退職,
            人("所得税_上場株式等に係る配当所得等の金額", period), 人("所得税_上場株式等に係る譲渡所得等の金額", period),
            人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period), 人("所得税_所得金額調整控除", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]  # fmt: skip
        _, after = _tokutei_rows(values, over, _rules2(parameters(period).所得税.所得金額調整控除.第2項))
        return _out([x.taishoku for x in after])


class 所得税_特定支出控除を当てた場合の分離課税の退職所得を除いた合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "特定支出控除を当てた場合の、退職所得がないものとして（公的年金等控除額の区分も）計算した合計所得金額（住民税の分離課税に係る退職所得のある人の"
        "合計所得金額：地方税法第292条第1項第13号・第313条第11項。JM-20・JM-23・JM-42。2分の1を超える特定支出のない人は0）"
    )
    reference = [f"{_PS8}#6", _TAISHOKU, _NENKIN]

    def formula_2025_01_01(人, period, parameters):
        over = 人("所得税_特定支出の額の合計額が給与所得控除額の2分の1を超えるか", period)
        if not np.any(over):
            return _zeros(over)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額", period), 人("所得税_雑所得の金額", period),
            人("所得税_公的年金等に係る雑所得の金額", period),
            人("所得税_特定支出控除を当てた場合の退職所得を除いた区分による公的年金等に係る雑所得の金額", period), 人("所得税_一時所得の金額", period),
            人("所得税_所得金額調整控除", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]  # fmt: skip
        masked = [np.where(over, np.asarray(v), 0) for v in values]
        rows, after = _jumin_rows(masked, _rules2(parameters(period).所得税.所得金額調整控除.第2項))
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row in zip(after, rounders, rows):
            ls = listed(row[7], row[8], 0, offset=bool(row[9]), carry=False)
            out.append(x.keijo + half_ichiji(x.ichiji, r) + ls.dividend_offset + ls.gain)
        return _out(out)


VARIABLES = (
    所得税_特定支出控除を当てた場合の回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額,
    所得税_特定支出控除を当てた場合の回収不能額等の前の総所得金額と退職所得金額の合計額,
    所得税_特定支出控除を当てた場合の回収不能額等の後の給与所得の金額,
    所得税_特定支出控除を当てた場合の公的年金等に係る雑所得以外の合計所得金額,
    所得税_特定支出控除を当てた場合の退職所得を除いた公的年金等に係る雑所得以外の合計所得金額,
    所得税_特定支出控除を当てた場合の合計所得金額,
    所得税_特定支出控除を当てた場合の損益通算の後の退職所得の金額,
    所得税_特定支出控除を当てた場合の分離課税の退職所得を除いた合計所得金額,
)

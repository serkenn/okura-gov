"""kyuyo への窓口（2026-11-12。rules/kyuyo/README.md KY-08）：未払の給与の回収不能（所得税法第64条第1項）の上限（施行令第180条第2項第1号）。

令180②一：回収不能額等が生じた時の直前において確定している総所得金額・退職所得金額・山林所得金額の合計額。所基通64−3 で、総所得金額は
損益通算の後の各種所得の金額（赤字の所得はないもの）の合計で、純損失・雑損失の繰越控除の後（docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md
§1.1・§1.3）。山林所得は範囲外（D20）。

「直前」の値なので、給与所得は回収不能額等を当てる前の額（kyuyo の 所得税_所得税法第64条第1項を当てる前の給与所得の金額）、公的年金等に係る雑所得は
その給与所得で求めた公的年金等控除額の区分による額（income_kinds の 所得税_回収不能額等の前の公的年金等に係る雑所得の金額）にする。
式は総所得金額・退職所得金額・総所得金額等と同じ関数（損益通算・一時所得の2分の1・繰越控除の順序）で、所得金額調整控除も同じ前の額から計算し直す。
kyuyo の段 未払の給与の回収不能 がこの値を読み、給与所得の金額（その段の出力に依存する）はここで引かない（段階評価の循環を断つ）。

所得金額調整控除の第1項の「扶養親族等を有するか」は personal_deductions の段がこの段の後で書くので、2つの値を出す：
所得税_回収不能額等の前の総所得金額と退職所得金額の合計額（第1項は本人が特別障害者に当たるときだけ）と、
所得税_所得金額調整控除の第1項を当てたとした…（給与等の収入金額が850万円を超えれば第1項を当てる）。
回収不能額等のない人だけの評価では計算しない（0）。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import adjustment_1, adjustment_2, apply_carryforwards, half_ichiji, listed, split_casualty
from .variables import _half_candidates_needed, _half_rounders, _ints, _offsets, _out, _rules1, _rules2

_SHOTOKU4 = "docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md"
_NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#2.1"
class 所得税_回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "給与所得を所得税法第64条第1項を当てる前の額にして計算した公的年金等に係る雑所得以外の合計所得金額（所法35④。所令180②一の総所得金額の"
        "公的年金等控除額の区分。式は 所得税_公的年金等に係る雑所得以外の合計所得金額 と同じ）"
    )
    reference = [_NENKIN, f"{_SHOTOKU4}#1.1"]

    def formula_2025_01_01(人, period, parameters):
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        if not np.any(回収不能 > 0):
            return np.zeros(len(回収不能), dtype=np.int32)
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_所得税法第64条第1項を当てる前の給与所得の金額", period)
        業務雑 = 人("所得税_業務に係る雑所得の金額", period)
        その他雑 = 人("所得税_その他の雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows = _ints(配当, 不動産, 事業, 給与, 業務雑, その他雑, 一時, 退職, 上場配当, 上場譲渡)
        after = _offsets([(a, b, c, d, e1 + e2, f, g) for a, b, c, d, e1, e2, f, g, _, _ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            ls = listed(row[8], row[9], 0, offset=bool(o), carry=False)
            out.append(x.keijo + half_ichiji(x.ichiji, r) + x.taishoku + ls.dividend_offset + ls.gain)
        return _out(out)


def _pre_rows(values: list, 特別障害者: object, first_paragraph_always: bool, p: object) -> tuple[list, list]:
    """行（配当・不動産・事業・給与〔64①の前〕・業務雑・その他雑・年金〔64①の前〕・一時・退職・上場配当・上場譲渡・上場繰越控除額・繰り越された純損失・
    繰り越された雑損失・給与等の収入金額・給与所得控除後の給与等の金額〔第2項の給与の側。特定支出控除の前：kyuyo KY-11、2026-11-12〕）と損益通算の結果。所得金額調整控除は前の給与所得・年金で計算し直す（first_paragraph_always は第1項の
    「有するか」を真とみなすか）。"""
    rules1, rules2 = _rules1(p), _rules2(p.第2項)  # type: ignore[attr-defined]
    rows = _ints(*values)
    adj = [
        adjustment_1(row[14], first_paragraph_always or bool(s), rules1) + adjustment_2(row[15], row[6], rules2)
        for row, s in zip(rows, 特別障害者)  # type: ignore[call-overload]
    ]
    after = _offsets([(a, b, c, d - j, e1 + e2 + n, f, g) for (a, b, c, d, e1, e2, n, f, g, *_), j in zip(rows, adj)])
    return rows, after


def _pre_totals(rows: list, after: list, rounders: list, 通算: object) -> np.ndarray:
    """所令180②一の合計額（総所得金額＋退職所得金額。繰越控除の後：所基通64−3。順序は総所得金額等の式と同じ）。"""
    out = []
    for x, r, row, o in zip(after, rounders, rows, 通算):  # type: ignore[call-overload]
        total = x.keijo + half_ichiji(x.ichiji, r)
        net = apply_carryforwards(total, x.taishoku, row[12], 0).net
        ls = listed(row[9], row[10], row[11], offset=bool(o), carry=True)
        sp = split_casualty(total, x.taishoku, ls.dividend_final, ls.gain_final, net, row[13])
        gross = total - min(total, net) - sp.from_total
        retirement = x.taishoku - (net - min(total, net)) - sp.from_retirement
        out.append(gross + retirement)
    return _out(out)


class 所得税_回収不能額等の前の総所得金額と退職所得金額の合計額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "所得税法施行令第180条第2項第1号の合計額：回収不能額等が生じた時の直前において確定している総所得金額と退職所得金額の合計（損益通算・繰越控除の後。"
        "所得金額調整控除の第1項は本人が特別障害者に当たるときだけ当てる。山林所得は範囲外）"
    )
    reference = [f"{_SHOTOKU4}#1.1", f"{_SHOTOKU4}#1.3"]

    def formula_2025_01_01(人, period, parameters):
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        if not np.any(回収不能 > 0):
            return np.zeros(len(回収不能), dtype=np.int32)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_所得税法第64条第1項を当てる前の給与所得の金額", period), 人("所得税_業務に係る雑所得の金額", period),
            人("所得税_その他の雑所得の金額", period), 人("所得税_回収不能額等の前の公的年金等に係る雑所得の金額", period),
            人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の繰越控除額", period),
            人("所得税_繰り越された純損失の金額", period), 人("所得税_繰り越された雑損失の金額", period), 人("所得税_給与等の収入金額", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]
        特別障害者 = 人("所得税_特別障害者に当たるか", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows, after = _pre_rows(values, 特別障害者, False, parameters(period).所得税.所得金額調整控除)
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _pre_totals(rows, after, _half_rounders(period, 候補, len(rows)), 通算)


class 所得税_所得金額調整控除の第1項を当てたとした回収不能額等の前の総所得金額と退職所得金額の合計額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "所得税_回収不能額等の前の総所得金額と退職所得金額の合計額 を、所得金額調整控除の第1項の要件（扶養親族等を有するか）を満たすとして計算した額"
        "（その判定は kyuyo の段の後にしか決まらないので、なかったものとみなす額が変わるかを確かめるための値）"
    )
    reference = [f"{_SHOTOKU4}#1.1", "docs/public-sources/20261109_round2_gaps-sources.md#3.1"]

    def formula_2025_01_01(人, period, parameters):
        回収不能 = 人("所得税_回収することができないこととなった給与等の金額", period)
        if not np.any(回収不能 > 0):
            return np.zeros(len(回収不能), dtype=np.int32)
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period),
            人("所得税_所得税法第64条第1項を当てる前の給与所得の金額", period), 人("所得税_業務に係る雑所得の金額", period),
            人("所得税_その他の雑所得の金額", period), 人("所得税_回収不能額等の前の公的年金等に係る雑所得の金額", period),
            人("所得税_一時所得の金額", period), 人("所得税_退職所得の金額", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の繰越控除額", period),
            人("所得税_繰り越された純損失の金額", period), 人("所得税_繰り越された雑損失の金額", period), 人("所得税_給与等の収入金額", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows, after = _pre_rows(values, [False] * len(回収不能), True, parameters(period).所得税.所得金額調整控除)
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        return _pre_totals(rows, after, _half_rounders(period, 候補, len(rows)), 通算)


VARIABLES = (
    所得税_回収不能額等の前の公的年金等に係る雑所得以外の合計所得金額,
    所得税_回収不能額等の前の総所得金額と退職所得金額の合計額,
    所得税_所得金額調整控除の第1項を当てたとした回収不能額等の前の総所得金額と退職所得金額の合計額,
)

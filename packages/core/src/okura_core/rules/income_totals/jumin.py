"""住民税への窓口（2026-11-12。rules/juminzei/README.md JM-19・JM-20・JM-23）：分離課税に係る退職所得を除いた所得の合計。

住民税では、所得税の源泉徴収の対象となる退職手当等の退職所得は他の所得と区分して課税し（地方税法第328条）、前年の所得（第313条第1項の
総所得金額・退職所得金額）と合計所得金額（第292条第1項第13号）に入れない（docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §6.1・§6.3）。
その計算は「所得税の計算の例」（第313条第2項）によるので、損益通算・繰越控除は分離課税に係る退職所得がないものとして当て、公的年金等控除額の区分
（公的年金等に係る雑所得以外の合計所得金額）も分離課税に係る退職所得を除いて求める（施行令第48条の5の2 の読替え：juminzei の README §6）。

ここでは「退職所得がないものとして」計算した値を出す（退職手当等の全部が源泉徴収の対象の人に juminzei が使う。そうでない人には所得税の値を使う）。
繰越控除の額は、所得税の申告の記載から作った繰り越された損失の額（所得税_繰り越された純損失の金額・雑損失の金額）を使う（住民税の繰越の額を記載した記録が
中間表現にない。法令の読み：basis.JUMIN_WINDOW_RULE）。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import adjustment_2, apply_carryforwards, half_ichiji, listed, split_casualty
from .variables import _half_candidates_needed, _half_rounders, _ints, _offsets, _out, _rules2

_TAISHOKU = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#6.3"
_NENKIN = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#2.1"


class 所得税_損益通算の後の退職所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益通算の後・繰越控除の前の退職所得の金額（合計所得金額に入る退職所得の部分。住民税の合計所得金額から除く額：JM-20）"
    reference = [_TAISHOKU]

    def formula_2025_01_01(人, period, parameters):
        退職 = 人("所得税_退職所得の金額", period)
        if not np.any(退職 != 0):
            return np.zeros(len(退職), dtype=np.int32)
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj in rows])
        return _out([x.taishoku for x in after])


class 所得税_退職所得を除いた公的年金等に係る雑所得以外の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職所得がないものとして計算した公的年金等に係る雑所得以外の合計所得金額（住民税の公的年金等控除額の区分：JM-23）"
    reference = [_NENKIN, _TAISHOKU]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        業務雑 = 人("所得税_業務に係る雑所得の金額", period)
        その他雑 = 人("所得税_その他の雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows = _ints(配当, 不動産, 事業, 給与, 業務雑, その他雑, 一時, 上場配当, 上場譲渡)
        after = _offsets([(a, b, c, d, e1 + e2, f, 0) for a, b, c, d, e1, e2, f, _, _ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            ls = listed(row[7], row[8], 0, offset=bool(o), carry=False)
            out.append(x.keijo + half_ichiji(x.ichiji, r) + ls.dividend_offset + ls.gain)
        return _out(out)


def _jumin_rows(values, rules):  # noqa: ANN001, ANN202
    """退職所得を0にし、公的年金等に係る雑所得を住民税の区分による額にした行と、損益通算の結果。values は 配当・不動産・事業・給与・雑・公的年金等の雑・住民税の区分の公的年金等の雑・一時・調整・上場配当・上場譲渡・通算・給与所得控除後の給与等の金額 の順の配列。
    所得金額調整控除の第2項は公的年金等に係る雑所得の金額に依存するので、その額で計算し直す（第1項はそのまま）。
    第2項の給与の側は給与所得控除後の給与等の金額（特定支出控除の前：kyuyo KY-11。2026-11-12 に足した。以前は給与所得の金額）。"""
    rows = []
    for a, b, c, d, e, n, nj, f, adj, ld, lg, o, w in _ints(*values):
        adj_j = adj - adjustment_2(w, n, rules) + adjustment_2(w, nj, rules) if nj != n else adj
        rows.append((a, b, c, d - adj_j, e - n + nj, f, 0, ld, lg, o))
    return rows, _offsets([r[:7] for r in rows])


def _after_carry(rows, after, rounders, carried):  # noqa: ANN001, ANN202
    """繰越控除の後の (総所得金額, 上場配当, 上場譲渡)。退職所得がないので、繰越控除は総所得金額（雑損失は上場分にも）からだけ控除する（所令201・204 の順）。"""
    out = []
    for x, r, row, (net_c, cas_c, lc) in zip(after, rounders, rows, carried):
        total = x.keijo + half_ichiji(x.ichiji, r)
        cf = apply_carryforwards(total, 0, net_c, 0)
        ls = listed(row[7], row[8], lc, offset=bool(row[9]), carry=True)
        sp = split_casualty(total, 0, ls.dividend_final, ls.gain_final, cf.net, cas_c)
        out.append((total - cf.net - sp.from_total, ls.dividend_final - sp.from_dividend, ls.gain_final - sp.from_gain))
    return out


class 所得税_分離課税の退職所得を除いた合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職所得がないものとして（公的年金等控除額の区分も）計算した合計所得金額（住民税の合計所得金額：地方税法第292条第1項第13号。JM-20・JM-23）"
    reference = [_TAISHOKU, _NENKIN]

    def formula_2025_01_01(人, period, parameters):
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period), 人("所得税_給与所得", period),
            人("所得税_雑所得の金額", period), 人("所得税_公的年金等に係る雑所得の金額", period),
            人("所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額", period), 人("所得税_一時所得の金額", period),
            人("所得税_所得金額調整控除", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]
        rows, after = _jumin_rows(values, _rules2(parameters(period).所得税.所得金額調整控除.第2項))
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row in zip(after, rounders, rows):
            ls = listed(row[7], row[8], 0, offset=bool(row[9]), carry=False)
            out.append(x.keijo + half_ichiji(x.ichiji, r) + ls.dividend_offset + ls.gain)
        return _out(out)


class 所得税_分離課税の退職所得を除いた総所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職所得がないものとして（公的年金等控除額の区分も）計算した総所得金額（繰越控除の後。住民税の課税標準の総所得金額：第313条。JM-20・JM-23）"
    reference = [_TAISHOKU, _NENKIN]

    def formula_2025_01_01(人, period, parameters):
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period), 人("所得税_給与所得", period),
            人("所得税_雑所得の金額", period), 人("所得税_公的年金等に係る雑所得の金額", period),
            人("所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額", period), 人("所得税_一時所得の金額", period),
            人("所得税_所得金額調整控除", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]
        rows, after = _jumin_rows(values, _rules2(parameters(period).所得税.所得金額調整控除.第2項))
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        carried = _ints(人("所得税_繰り越された純損失の金額", period), 人("所得税_繰り越された雑損失の金額", period), 人("所得税_上場株式等の譲渡損失の繰越控除額", period))
        return _out([t for t, _, _ in _after_carry(rows, after, rounders, carried)])


class 所得税_分離課税の退職所得を除いた総所得金額等(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職所得がないものとして計算した総所得金額等（総所得金額＋申告分離課税の上場株式等の所得。繰越控除の後。住民税の総所得金額等。JM-20・JM-23）"
    reference = [_TAISHOKU, _NENKIN]

    def formula_2025_01_01(人, period, parameters):
        values = [
            人("所得税_配当所得の金額", period), 人("所得税_不動産所得の金額", period), 人("所得税_事業所得の金額", period), 人("所得税_給与所得", period),
            人("所得税_雑所得の金額", period), 人("所得税_公的年金等に係る雑所得の金額", period),
            人("所得税_退職所得を除いた区分による公的年金等に係る雑所得の金額", period), 人("所得税_一時所得の金額", period),
            人("所得税_所得金額調整控除", period), 人("所得税_上場株式等に係る配当所得等の金額", period),
            人("所得税_上場株式等に係る譲渡所得等の金額", period), 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period),
            人("所得税_給与所得控除後の給与等の金額", period),
        ]
        rows, after = _jumin_rows(values, _rules2(parameters(period).所得税.所得金額調整控除.第2項))
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        carried = _ints(人("所得税_繰り越された純損失の金額", period), 人("所得税_繰り越された雑損失の金額", period), 人("所得税_上場株式等の譲渡損失の繰越控除額", period))
        return _out([t + d + g for t, d, g in _after_carry(rows, after, rounders, carried)])


VARIABLES = (
    所得税_損益通算の後の退職所得の金額,
    所得税_退職所得を除いた公的年金等に係る雑所得以外の合計所得金額,
    所得税_分離課税の退職所得を除いた合計所得金額,
    所得税_分離課税の退職所得を除いた総所得金額,
    所得税_分離課税の退職所得を除いた総所得金額等,
)

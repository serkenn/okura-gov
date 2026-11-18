"""申告書の欄に写す途中の値（2026-11-12。様式の欄の対応表 forms が写す。計算は法令の式の途中の値をそのまま出すだけ）。

- 一時所得：特別控除の前の差引金額（総収入金額 − 支出した金額）と特別控除額（所法34②③）。第二表「総合課税の譲渡所得、一時所得に関する事項」
  の差引金額、第四表（一）の 72 の Ⓒ・Ⓓ（docs/public-sources/20261109_round2_yoshiki-forms-r07.md §3・§5.1）。
- 退職所得：退職手当等の区分（一般・短期・特定役員）ごとの収入金額と退職所得控除額（所法30②③⑥⑦、所令71の2）。第三表「退職所得に関する事項」の
  3行（同 §4）。一つの区分だけなら、その区分の行に収入金額の全部と退職所得控除額の全部。二以上の区分なら、短期・特定役員の入力の額と、一般は残り
  （所令71の2 の一般退職所得控除額：退職所得控除額から特定役員退職所得控除額・短期退職所得控除額を控除した額。⑤の短期と特定役員だけのときは、
  短期退職所得控除額は退職所得控除額から特定役員退職所得控除額を控除した額。calc.retirement_income_multi と同じ）。
"""

from __future__ import annotations

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from .calc import RETIRE_GENERAL, RETIRE_OFFICER, RETIRE_SHORT, retirement_deduction, retirement_rules
from .variables import JIGYO, TAISHOKU, _yen


class 所得税_一時所得の特別控除前の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一時所得の総収入金額から収入を得るために支出した金額を控除した金額（特別控除の前。所得税法第34条第2項。負になりうる）"
    reference = [f"{JIGYO}#6"]

    def formula_2025_01_01(人, period, parameters):
        総収入 = 人("所得税_一時所得の総収入金額", period)
        支出 = 人("所得税_一時所得の支出した金額", period)
        return _yen([int(t) - int(e) for t, e in zip(総収入, 支出)], "一時所得の特別控除前の金額")


class 所得税_一時所得の特別控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一時所得の特別控除額（所得税法第34条第3項：五十万円。残額が五十万円に満たなければ当該残額。残額が0以下なら0）"
    reference = [f"{JIGYO}#6"]

    def formula_2025_01_01(人, period, parameters):
        総収入 = 人("所得税_一時所得の総収入金額", period)
        支出 = 人("所得税_一時所得の支出した金額", period)
        special = int(parameters(period).所得税.一時所得.特別控除額)
        return _yen([min(special, max(0, int(t) - int(e))) for t, e in zip(総収入, 支出)], "一時所得の特別控除額")


def _retirement_rows(収入, 年数, 区分, 障害, 前, 短期額, 役員額, 短期控除, 役員控除, r) -> list[dict[str, tuple[int, int]]]:  # noqa: ANN001
    """人ごとに 区分 → (収入金額, 退職所得控除額)。引数は人ごとの配列と retirement_rules の値。"""
    out: list[dict[str, tuple[int, int]]] = []
    for a, y, k, d, q, s, o, sd, od in zip(収入, 年数, 区分, 障害, 前, 短期額, 役員額, 短期控除, 役員控除):
        a, s, o, sd, od = int(a), int(s), int(o), int(sd), int(od)
        row = {RETIRE_GENERAL: (0, 0), RETIRE_SHORT: (0, 0), RETIRE_OFFICER: (0, 0)}
        if a:
            total = retirement_deduction(max(1, int(y)), bool(d), r, int(q))
            if s or o:  # 二以上の区分（所法30⑦・所令71の2）
                g = a - s - o
                if o == 0:  # ① 一般＋短期
                    row = {RETIRE_GENERAL: (g, total - sd), RETIRE_SHORT: (s, sd), RETIRE_OFFICER: (0, 0)}
                elif s == 0:  # ③ 一般＋特定役員
                    row = {RETIRE_GENERAL: (g, total - od), RETIRE_SHORT: (0, 0), RETIRE_OFFICER: (o, od)}
                elif g == 0:  # ⑤ 短期＋特定役員
                    row = {RETIRE_GENERAL: (0, 0), RETIRE_SHORT: (s, total - od), RETIRE_OFFICER: (o, od)}
                else:  # ⑦ 三つとも
                    row = {RETIRE_GENERAL: (g, total - od - sd), RETIRE_SHORT: (s, sd), RETIRE_OFFICER: (o, od)}
            else:
                row[str(k)] = (a, total)
        out.append(row)
    return out

class 所得税_退職所得の一般の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一般退職手当等の収入金額（第三表の退職所得に関する事項の一般の行。所法30②⑦）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        rows = _retirement_rows(
            収入,
            人("所得税_退職所得の勤続年数", period),
            人("所得税_退職手当等の区分", period),
            人("所得税_障害者になったことに直接基因する退職か", period),
            人("所得税_前の退職手当等との重複年数", period),
            人("所得税_短期退職手当等の収入金額", period),
            人("所得税_特定役員退職手当等の収入金額", period),
            人("所得税_短期退職所得控除額", period),
            人("所得税_特定役員退職所得控除額", period),
            retirement_rules(parameters(period)),
        )
        return _yen([row[RETIRE_GENERAL][0] for row in rows], "所得税_退職所得の一般の収入金額")



class 所得税_退職所得の一般の退職所得控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "一般退職手当等に係る退職所得控除額（一般の行。所法30③⑥、所令71の2 の一般退職所得控除額）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        rows = _retirement_rows(
            収入,
            人("所得税_退職所得の勤続年数", period),
            人("所得税_退職手当等の区分", period),
            人("所得税_障害者になったことに直接基因する退職か", period),
            人("所得税_前の退職手当等との重複年数", period),
            人("所得税_短期退職手当等の収入金額", period),
            人("所得税_特定役員退職手当等の収入金額", period),
            人("所得税_短期退職所得控除額", period),
            人("所得税_特定役員退職所得控除額", period),
            retirement_rules(parameters(period)),
        )
        return _yen([row[RETIRE_GENERAL][1] for row in rows], "所得税_退職所得の一般の退職所得控除額")



class 所得税_退職所得の短期の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "短期退職手当等の収入金額（第三表の退職所得に関する事項の短期の行。所法30④）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        rows = _retirement_rows(
            収入,
            人("所得税_退職所得の勤続年数", period),
            人("所得税_退職手当等の区分", period),
            人("所得税_障害者になったことに直接基因する退職か", period),
            人("所得税_前の退職手当等との重複年数", period),
            人("所得税_短期退職手当等の収入金額", period),
            人("所得税_特定役員退職手当等の収入金額", period),
            人("所得税_短期退職所得控除額", period),
            人("所得税_特定役員退職所得控除額", period),
            retirement_rules(parameters(period)),
        )
        return _yen([row[RETIRE_SHORT][0] for row in rows], "所得税_退職所得の短期の収入金額")



class 所得税_退職所得の短期の退職所得控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "短期退職手当等に係る退職所得控除額（短期の行。所令71の2 の短期退職所得控除額）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        rows = _retirement_rows(
            収入,
            人("所得税_退職所得の勤続年数", period),
            人("所得税_退職手当等の区分", period),
            人("所得税_障害者になったことに直接基因する退職か", period),
            人("所得税_前の退職手当等との重複年数", period),
            人("所得税_短期退職手当等の収入金額", period),
            人("所得税_特定役員退職手当等の収入金額", period),
            人("所得税_短期退職所得控除額", period),
            人("所得税_特定役員退職所得控除額", period),
            retirement_rules(parameters(period)),
        )
        return _yen([row[RETIRE_SHORT][1] for row in rows], "所得税_退職所得の短期の退職所得控除額")



class 所得税_退職所得の特定役員の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定役員退職手当等の収入金額（第三表の退職所得に関する事項の特定役員の行。所法30⑤）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        rows = _retirement_rows(
            収入,
            人("所得税_退職所得の勤続年数", period),
            人("所得税_退職手当等の区分", period),
            人("所得税_障害者になったことに直接基因する退職か", period),
            人("所得税_前の退職手当等との重複年数", period),
            人("所得税_短期退職手当等の収入金額", period),
            人("所得税_特定役員退職手当等の収入金額", period),
            人("所得税_短期退職所得控除額", period),
            人("所得税_特定役員退職所得控除額", period),
            retirement_rules(parameters(period)),
        )
        return _yen([row[RETIRE_OFFICER][0] for row in rows], "所得税_退職所得の特定役員の収入金額")



class 所得税_退職所得の特定役員の退職所得控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "特定役員退職手当等に係る退職所得控除額（特定役員の行。所令71の2 の特定役員退職所得控除額）"
    reference = [f"{TAISHOKU}#2.1", f"{TAISHOKU}#2.4"]

    def formula_2025_01_01(人, period, parameters):
        収入 = 人("所得税_退職手当等の収入金額", period)
        if not np.any(収入 > 0):
            return np.zeros(len(収入), dtype=np.int32)
        rows = _retirement_rows(
            収入,
            人("所得税_退職所得の勤続年数", period),
            人("所得税_退職手当等の区分", period),
            人("所得税_障害者になったことに直接基因する退職か", period),
            人("所得税_前の退職手当等との重複年数", period),
            人("所得税_短期退職手当等の収入金額", period),
            人("所得税_特定役員退職手当等の収入金額", period),
            人("所得税_短期退職所得控除額", period),
            人("所得税_特定役員退職所得控除額", period),
            retirement_rules(parameters(period)),
        )
        return _yen([row[RETIRE_OFFICER][1] for row in rows], "所得税_退職所得の特定役員の退職所得控除額")


VARIABLES = (
    所得税_一時所得の特別控除前の金額,
    所得税_一時所得の特別控除額,
    所得税_退職所得の一般の収入金額,
    所得税_退職所得の一般の退職所得控除額,
    所得税_退職所得の短期の収入金額,
    所得税_退職所得の短期の退職所得控除額,
    所得税_退職所得の特定役員の収入金額,
    所得税_退職所得の特定役員の退職所得控除額,
)

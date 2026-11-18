"""申告書の欄に写す途中の値（2026-11-12。様式の欄の対応表 forms が第四表（損失申告用）・第三表に写す）。

損益の通算の段階（第四表（一）の「2 損益の通算」。docs/public-sources/20261109_round2_yoshiki-forms-r07.md §5.1・§5.3）：
所令198 の順序（calc.offset_losses と同じ）で、Ⓐ通算前 → Ⓑ第1次通算後（経常所得の損失を譲渡・一時から：三号。総合譲渡は後の段で、一時所得だけ）
→ Ⓒ第2次通算後（山林所得から：五号。山林所得は範囲外なので Ⓑ と同じ）→ Ⓓ第3次通算後（退職所得から：五号）→ Ⓔ。
一時所得の Ⓔ は2分の1（所法22②二）の後の額とする（法令の読み：第四表 93 の計算式は 81〔Ⓔ の合計〕を総所得金額等の材料にする〔§5.3〕ので、
81 が総所得金額＋退職所得金額〔繰越控除の前〕になるには一時所得の Ⓔ が2分の1の後でなければならない）。
81 は Ⓔ の合計（赤字は負）：損失が残れば −純損失の金額。

繰越損失の年分ごとの内訳（第四表（二）の「4 繰越損失を差し引く計算」の Ⓑ・Ⓒ。§5.3「古い年分から順に差し引く」「純損失と雑損失があるときは
純損失を先」）：純損失・雑損失の繰越控除額（variables.py。所令201・204 の順序で決まる合計）を、生じた年分の古い順に割り振る。
Ⓒ（翌年分以後に繰り越して差し引かれる損失額）は 2年前・前年の年分の Ⓐ−Ⓑ（3年前の年分は翌年に繰り越せない：所法70①・71①）。

上場株式等の譲渡損失（措法37の12の2、措令25の11の2⑧：docs/public-sources/20261109_round2b_kabu-law-and-nta.md §6）：繰越控除額のうち譲渡所得等から
控除した額と配当所得等から控除した額（⑧二：まず譲渡所得等から）、翌年以後に繰り越す額（その年の譲渡損失のうち①で控除しきれない額＋2年前・前年の
年分に生じた繰り越された損失のうち控除しきれない額。⑧一：最も古い年の損失から控除する）。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from .calc import adjustment_1, adjustment_2, half_ichiji, listed
from .inputs import V_CASUALTY_BY_YEAR, V_LISTED_BY_YEAR, V_NET_BY_YEAR
from .variables import _half_candidates_needed, _half_rounders, _ints, _offsets, _rules1, _rules2

_YS = "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#5.3"
_YS1 = "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#5.1"
_YS2 = "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#5.2"
_GENKA = "docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.1"
_AO = "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.2"
_SS = "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#8"
_KABU6 = "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#6"


def _signed(values: Sequence[int], what: str) -> np.ndarray:
    for v in values:
        if abs(v) > INT32_MAX:
            raise OverflowError(f"{what} が int32 の範囲の外: {v}")
    return np.array(values, dtype=np.int32)


def _input(name: str, label: str, refs: list[str]) -> type:
    return type(name, (Variable,), {"value_type": int, "entity": 人物, "definition_period": YEAR, "label": label, "reference": refs, "__module__": __name__})


# ---------------------------------------------------------------------------
# 純粋関数
# ---------------------------------------------------------------------------


def keijo_before(haito: int, fudosan: int, jigyo: int, kyuyo: int, zatsu: int) -> int:
    """損益の通算の前の経常所得の金額（calc.offset_losses と同じ：配当所得・雑所得の損失は0。所法69①）。"""
    return max(haito, 0) + fudosan + jigyo + kyuyo + max(zatsu, 0)


def first_offset(keijo: int, ichiji: int) -> tuple[int, int]:
    """第1次通算（所令198三。総合譲渡は後の段なので一時所得だけ）：経常所得の損失を一時所得から控除した後の（経常所得, 一時所得）。

    計算例：経常 −500,000・一時 200,000 → (−300,000, 0)。経常 −100,000・一時 300,000 → (0, 200,000)。経常が黒字ならそのまま。
    """
    ichiji = max(ichiji, 0)
    if keijo >= 0:
        return keijo, ichiji
    d = min(-keijo, ichiji)
    return keijo + d, ichiji - d


def oldest_first(total: int, amounts: Sequence[int]) -> list[int]:
    """控除した額 total を、生じた年分の古い順（amounts の順）に割り振る（手引き 損失申告用「古い年分から順に差し引く」、措令25の11の2⑧一）。

    計算例：total 500,000、(300,000, 400,000, 100,000) → (300,000, 200,000, 0)。total が合計を超えれば ValueError（呼ぶ側の誤り）。
    """
    if total < 0 or any(a < 0 for a in amounts) or total > sum(amounts):
        raise ValueError(f"割り振れない：控除した額 {total}、年分ごとの額 {list(amounts)}")
    out = []
    rest = total
    for a in amounts:
        d = min(rest, a)
        out.append(d)
        rest -= d
    return out


def listed_split(dividend: int, gain_or_loss: int, carried: int, *, offset: bool, carry: bool) -> tuple[int, int, int]:
    """上場株式等：(繰越控除額のうち譲渡所得等から控除した額, 配当所得等から控除した額, その年に生じた譲渡損失のうち①で控除しきれない額)。"""
    ls = listed(dividend, gain_or_loss, carried, offset=offset, carry=carry)
    from_gain = min(ls.carry, ls.gain)
    loss = max(-gain_or_loss, 0)
    used_by_offset = max(dividend, 0) - ls.dividend_offset
    return from_gain, ls.carry - from_gain, loss - used_by_offset


# ---------------------------------------------------------------------------
# 入力変数（inputs.py が前年以前の申告書の記載から書く）
# ---------------------------------------------------------------------------

_LABEL_YEAR = {0: "3年前の年分", 1: "2年前の年分", 2: "前年分"}
_NET_INPUTS = tuple(
    _input(v, f"繰り越された純損失の金額のうち{_LABEL_YEAR[i]}に生じたもの（所法70①。第四表（二）4 の Ⓐ）", [_AO, _YS])
    for i, v in enumerate(V_NET_BY_YEAR)
)
_CASUALTY_INPUTS = tuple(
    _input(v, f"繰り越された雑損失の金額のうち{_LABEL_YEAR[i]}に生じたもの（所法71①。第四表（二）4 の Ⓐ）", [_SS, _YS])
    for i, v in enumerate(V_CASUALTY_BY_YEAR)
)
_LISTED_INPUTS = tuple(
    _input(v, f"繰り越された上場株式等の譲渡損失の金額のうち{_LABEL_YEAR[i]}に生じたもの（措法37の12の2⑤）", [_KABU6])
    for i, v in enumerate(V_LISTED_BY_YEAR)
)


# ---------------------------------------------------------------------------
# 損益の通算の段階（第四表（一）2）
# ---------------------------------------------------------------------------


class 所得税_損益の通算の前の経常所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益の通算の前の経常所得の金額（第四表（一）2 の 67 の Ⓐ。給与所得は所得金額調整控除の後。負になりうる）"
    reference = [_GENKA, _YS]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        return _signed([keijo_before(a, b, c, d - adj, e) for a, b, c, d, e, adj in _ints(配当, 不動産, 事業, 給与, 雑, 調整)], "経常所得")


class 所得税_損益の通算の第1次通算後の経常所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益の通算の第1次通算後の経常所得の金額（所令198三：一時所得から控除した後。第四表（一）2 の 67 の Ⓑ・Ⓒ。負になりうる）"
    reference = [_GENKA, _YS]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 調整)
        return _signed([first_offset(keijo_before(a, b, c, d - adj, e), f)[0] for a, b, c, d, e, f, adj in rows], "経常所得")


class 所得税_損益の通算の第1次通算後の一時所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益の通算の第1次通算後の一時所得の金額（所令198三。2分の1の前。第四表（一）2 の 72 の Ⓑ・Ⓒ・Ⓓ）"
    reference = [_GENKA, _YS]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 調整)
        return _signed([first_offset(keijo_before(a, b, c, d - adj, e), f)[1] for a, b, c, d, e, f, adj in rows], "一時所得")


class 所得税_損益の通算の第3次通算後の経常所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益の通算の第3次通算後の経常所得の金額（所令198五：退職所得から控除した後。損失が残れば −純損失の金額。第四表（一）2 の 67 の Ⓓ・Ⓔ）"
    reference = [_GENKA, _YS]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj in rows])
        return _signed([-x.net_loss if x.net_loss else x.keijo for x in after], "経常所得")


class 所得税_損益の通算の後の一時所得の2分の1の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益の通算の後の一時所得の金額の2分の1（所法22②二。第四表（一）2 の 72 の Ⓔ：法令の読み）"
    reference = [_GENKA, _YS]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        return _signed([half_ichiji(x.ichiji, r) for x, r in zip(after, rounders)], "一時所得の2分の1")


class 所得税_損益の通算の後の損失額又は所得金額の合計額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "損益の通算の後の損失額又は所得金額の合計額（第四表（一）81：Ⓔ の合計。損失が残れば −純損失の金額）"
    reference = [_GENKA, _YS]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r in zip(after, rounders):
            out.append(-x.net_loss if x.net_loss else x.keijo + half_ichiji(x.ichiji, r) + x.taishoku)
        return _signed(out, "損益の通算の後の合計額")


# ---------------------------------------------------------------------------
# 繰越損失の年分ごとの内訳（第四表（二）4 の Ⓑ・Ⓒ）
# ---------------------------------------------------------------------------


class 所得税_純損失の繰越控除額のうち3年前の年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "純損失の繰越控除額のうち3年前の年分に生じたもの（古い年分から順に差し引く。第四表（二）4 の年分 A の Ⓑ）"
    reference = [_AO, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_純損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された純損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された純損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された純損失の金額", period)
        return _signed([oldest_first(t, (x, y, z))[0] for t, x, y, z in _ints(控除, a, b, c)], "純損失の繰越控除額")


class 所得税_純損失の繰越控除額のうち2年前の年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "純損失の繰越控除額のうち2年前の年分に生じたもの（第四表（二）4 の年分 B の Ⓑ）"
    reference = [_AO, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_純損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された純損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された純損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された純損失の金額", period)
        return _signed([oldest_first(t, (x, y, z))[1] for t, x, y, z in _ints(控除, a, b, c)], "純損失の繰越控除額")


class 所得税_純損失の繰越控除額のうち前年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "純損失の繰越控除額のうち前年分に生じたもの（第四表（二）4 の年分 C の Ⓑ）"
    reference = [_AO, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_純損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された純損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された純損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された純損失の金額", period)
        return _signed([oldest_first(t, (x, y, z))[2] for t, x, y, z in _ints(控除, a, b, c)], "純損失の繰越控除額")


class 所得税_翌年以後に繰り越す純損失の金額のうち2年前の年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "繰り越された純損失のうち2年前の年分に生じたもので控除しきれない額（第四表（二）4 の年分 B の Ⓒ＝Ⓐ−Ⓑ）"
    reference = [_AO, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_純損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された純損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された純損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された純損失の金額", period)
        return _signed([y - oldest_first(t, (x, y, z))[1] for t, x, y, z in _ints(控除, a, b, c)], "純損失")


class 所得税_翌年以後に繰り越す純損失の金額のうち前年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "繰り越された純損失のうち前年分に生じたもので控除しきれない額（第四表（二）4 の年分 C の Ⓒ＝Ⓐ−Ⓑ）"
    reference = [_AO, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_純損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された純損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された純損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された純損失の金額", period)
        return _signed([z - oldest_first(t, (x, y, z))[2] for t, x, y, z in _ints(控除, a, b, c)], "純損失")


class 所得税_雑損失の繰越控除額のうち3年前の年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "雑損失の繰越控除額のうち3年前の年分に生じたもの（第四表（二）4 の年分 A の Ⓑ）"
    reference = [_SS, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_雑損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された雑損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された雑損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された雑損失の金額", period)
        return _signed([oldest_first(t, (x, y, z))[0] for t, x, y, z in _ints(控除, a, b, c)], "雑損失の繰越控除額")


class 所得税_雑損失の繰越控除額のうち2年前の年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "雑損失の繰越控除額のうち2年前の年分に生じたもの（第四表（二）4 の年分 B の Ⓑ）"
    reference = [_SS, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_雑損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された雑損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された雑損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された雑損失の金額", period)
        return _signed([oldest_first(t, (x, y, z))[1] for t, x, y, z in _ints(控除, a, b, c)], "雑損失の繰越控除額")


class 所得税_雑損失の繰越控除額のうち前年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "雑損失の繰越控除額のうち前年分に生じたもの（第四表（二）4 の年分 C の Ⓑ）"
    reference = [_SS, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_雑損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された雑損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された雑損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された雑損失の金額", period)
        return _signed([oldest_first(t, (x, y, z))[2] for t, x, y, z in _ints(控除, a, b, c)], "雑損失の繰越控除額")


class 所得税_翌年以後に繰り越す雑損失の金額のうち2年前の年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "繰り越された雑損失のうち2年前の年分に生じたもので控除しきれない額（第四表（二）4 の年分 B の Ⓒ＝Ⓐ−Ⓑ）"
    reference = [_SS, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_雑損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された雑損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された雑損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された雑損失の金額", period)
        return _signed([y - oldest_first(t, (x, y, z))[1] for t, x, y, z in _ints(控除, a, b, c)], "雑損失")


class 所得税_翌年以後に繰り越す雑損失の金額のうち前年分に生じたもの(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "繰り越された雑損失のうち前年分に生じたもので控除しきれない額（第四表（二）4 の年分 C の Ⓒ＝Ⓐ−Ⓑ）"
    reference = [_SS, _YS]

    def formula_2025_01_01(人, period, parameters):
        控除 = 人("所得税_雑損失の繰越控除額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された雑損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された雑損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された雑損失の金額", period)
        return _signed([z - oldest_first(t, (x, y, z))[2] for t, x, y, z in _ints(控除, a, b, c)], "雑損失")


# ---------------------------------------------------------------------------
# 上場株式等の譲渡損失（第三表 95〜97、第四表（二）90・91・95）
# ---------------------------------------------------------------------------


class 所得税_上場株式等の譲渡損失の繰越控除額のうち譲渡所得等から控除した額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る譲渡損失の繰越控除額のうち上場株式等に係る譲渡所得等の金額から控除した額（措令25の11の2⑧二。第三表 95、第四表（二）90）"
    reference = [_KABU6, _YS2]

    def formula_2025_01_01(人, period, parameters):
        繰越 = 人("所得税_繰り越された上場株式等の譲渡損失の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        適用 = 人("所得税_上場株式等の譲渡損失の繰越控除を適用するか", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        return _signed(
            [listed_split(d, g, c, offset=bool(o), carry=bool(a))[0] for (d, g, c), o, a in zip(_ints(上場配当, 上場譲渡, 繰越), 通算, 適用)],
            "上場株式等の譲渡損失の繰越控除額",
        )


class 所得税_上場株式等の譲渡損失の繰越控除額のうち配当所得等から控除した額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る譲渡損失の繰越控除額のうち上場株式等に係る配当所得等の金額から控除した額（措令25の11の2⑧二。第三表 97、第四表（二）91）"
    reference = [_KABU6, _YS2]

    def formula_2025_01_01(人, period, parameters):
        繰越 = 人("所得税_繰り越された上場株式等の譲渡損失の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        適用 = 人("所得税_上場株式等の譲渡損失の繰越控除を適用するか", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        return _signed(
            [listed_split(d, g, c, offset=bool(o), carry=bool(a))[1] for (d, g, c), o, a in zip(_ints(上場配当, 上場譲渡, 繰越), 通算, 適用)],
            "上場株式等の譲渡損失の繰越控除額",
        )


class 所得税_翌年以後に繰り越す上場株式等の譲渡損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "翌年以後に繰り越される上場株式等に係る譲渡損失の金額（措法37の12の2⑤⑦、措令25の11の2⑧一。第三表 96、第四表（二）95）"
    reference = [_KABU6, _YS2]

    def formula_2025_01_01(人, period, parameters):
        繰越 = 人("所得税_繰り越された上場株式等の譲渡損失の金額", period)
        a = 人("所得税_3年前の年分に生じた繰り越された上場株式等の譲渡損失の金額", period)
        b = 人("所得税_2年前の年分に生じた繰り越された上場株式等の譲渡損失の金額", period)
        c = 人("所得税_前年分に生じた繰り越された上場株式等の譲渡損失の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        適用 = 人("所得税_上場株式等の譲渡損失の繰越控除を適用するか", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        out = []
        for (total, x, y, z, d, g), o, ap in zip(_ints(繰越, a, b, c, 上場配当, 上場譲渡), 通算, 適用):
            from_gain, from_div, new = listed_split(d, g, total, offset=bool(o), carry=bool(ap))
            used = oldest_first(from_gain + from_div, (x, y, z))
            out.append(new + (y - used[1]) + (z - used[2]))
        return _signed(out, "翌年以後に繰り越す上場株式等の譲渡損失の金額")


_PS9 = "docs/public-sources/20261112_impl-research9_tokutei-jumin-sources.md#4.1"


class 所得税_所得金額調整控除の区分(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    default_value = "なし"
    label = (
        "第一表 ㋔（収入金額等の給与）の区分 G13：所得金額調整控除の第1項（手引き Step3 の(1)）に当たれば「1」、第2項（(2)）に当たれば「2」、両方なら「3」、"
        "どちらもなければ「なし」（確定申告の手引き 3-2_06。2026-11-12 の3回目）"
    )
    reference = [_PS9, "docs/public-sources/20261109_round2_gaps-sources.md#3.1"]

    def formula_2025_01_01(人, period, parameters):
        給与 = 人("所得税_給与所得控除後の給与等の金額", period)
        年金 = 人("所得税_公的年金等に係る雑所得の金額", period)
        収入 = 人("所得税_給与等の収入金額", period)
        特別障害者 = 人("所得税_特別障害者に当たるか", period)
        有する = 人("所得税_所得金額調整控除の対象の親族等を有するか", period)
        p = parameters(period).所得税.所得金額調整控除
        rules1, rules2 = _rules1(p), _rules2(p.第2項)
        out = []
        for (k, n, w), a, b in zip(_ints(給与, 年金, 収入), 特別障害者, 有する):
            code = (1 if adjustment_1(w, bool(a) or bool(b), rules1) > 0 else 0) + (2 if adjustment_2(k, n, rules2) > 0 else 0)
            out.append(str(code) if code else "なし")
        return np.array(out, dtype=object)


class 所得税_所得金額調整控除の後の給与所得の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "第一表 ⑥（所得金額等の給与）に書く給与所得の金額：手引き 3-2_06 の計算欄 J（C−(F＋I)：給与所得の金額から所得金額調整控除の額を引いた額。"
        "負なら0：損益通算で0 とする calc.offset_losses と同じ。2026-11-12 の3回目）"
    )
    reference = [_PS9, "docs/public-sources/20261109_round2_gaps-sources.md#3.1"]

    def formula_2025_01_01(人, period, parameters):
        給与 = 人("所得税_給与所得", period)
        調整 = 人("所得税_所得金額調整控除", period)
        return np.maximum(給与 - 調整, 0).astype(np.int32)


VARIABLES = (
    所得税_所得金額調整控除の区分,
    所得税_所得金額調整控除の後の給与所得の金額,
    *_NET_INPUTS,
    *_CASUALTY_INPUTS,
    *_LISTED_INPUTS,
    所得税_損益の通算の前の経常所得の金額,
    所得税_損益の通算の第1次通算後の経常所得の金額,
    所得税_損益の通算の第1次通算後の一時所得の金額,
    所得税_損益の通算の第3次通算後の経常所得の金額,
    所得税_損益の通算の後の一時所得の2分の1の金額,
    所得税_損益の通算の後の損失額又は所得金額の合計額,
    所得税_純損失の繰越控除額のうち3年前の年分に生じたもの,
    所得税_純損失の繰越控除額のうち2年前の年分に生じたもの,
    所得税_純損失の繰越控除額のうち前年分に生じたもの,
    所得税_翌年以後に繰り越す純損失の金額のうち2年前の年分に生じたもの,
    所得税_翌年以後に繰り越す純損失の金額のうち前年分に生じたもの,
    所得税_雑損失の繰越控除額のうち3年前の年分に生じたもの,
    所得税_雑損失の繰越控除額のうち2年前の年分に生じたもの,
    所得税_雑損失の繰越控除額のうち前年分に生じたもの,
    所得税_翌年以後に繰り越す雑損失の金額のうち2年前の年分に生じたもの,
    所得税_翌年以後に繰り越す雑損失の金額のうち前年分に生じたもの,
    所得税_上場株式等の譲渡損失の繰越控除額のうち譲渡所得等から控除した額,
    所得税_上場株式等の譲渡損失の繰越控除額のうち配当所得等から控除した額,
    所得税_翌年以後に繰り越す上場株式等の譲渡損失の金額,
)

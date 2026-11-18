"""規則モジュール income_totals の変数（所得の合計・損益通算・繰越控除・所得金額調整控除の第2項）。

式は calc.py の純粋関数を1人ずつ当てる（整数の円と Fraction。float は使わない）。集約点（合計所得金額・総所得金額・総所得金額等など）は
「集める先」の約束で所得の種類ごとの所得を直接引くので、損益通算は各式で同じ関数を呼ぶ（変数をまたいで途中の値を持たない）。

一時所得の2分の1の端数の候補（文字列の入力変数。evaluate が候補ごとに入れる）は、端数が出る人がいるときだけ引く。
端数が出ない評価では候補の分かれ目が値の入力に入らない（評価した分かれ目に出さない）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fractions import Fraction
from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from ...rounding import FUNCTIONS
from .calc import (
    Adjustment1Rules,
    Adjustment2Rules,
    CarrybackRules,
    AfterOffset,
    Incomes,
    adjustment_1,
    adjustment_2,
    apply_carryforwards,
    carryback_refund,
    second_prior_refund,
    split_casualty,
    ICHIJI_HALF_TEBIKI_YEARS,
    half_ichiji,
    listed,
    needs_rounding,
    offset_losses,
)

_GENKA = "docs/public-sources/20261109_round2_genka-laws-and-nta.md#6.1"
_GAPS = "docs/public-sources/20261109_round2_gaps-sources.md#3.1"
_KABU6 = "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#6"
_R1 = "docs/public-sources/20261109_R1-laws_income-tax.md#4"
_IRYOHI = "docs/public-sources/20261109_impl-prep_iryohi-law-text.md#3.1"
_JOTO = "docs/public-sources/20261111_impl-research_joto-junjo-laws.md#2.3"


def _ints(*arrays: Iterable[object]) -> list[tuple[int, ...]]:
    return [tuple(int(v) for v in row) for row in zip(*arrays)]


def _out(values: Sequence[int]) -> np.ndarray:
    for v in values:
        if not 0 <= v <= INT32_MAX:
            raise OverflowError(f"所得の合計が int32 の範囲（0〜{INT32_MAX}）の外: {v}")
    return np.array(values, dtype=np.int32)


def _rounders(candidates: object, n: int) -> list:
    """端数の候補の名前の配列 → 丸めの関数。候補を引いていない（端数が出ない）ときは、丸めを使わない関数を返す。"""
    if candidates is None:
        return [_no_rounding] * n
    return [FUNCTIONS[str(c)] for c in candidates]  # type: ignore[union-attr]


def _half_candidates_needed(period: object, after: Sequence[AfterOffset]) -> bool:
    """一時所得の2分の1の候補を引くか。手引きの注記がある年分は引かない。手引きのない年分も端数が出る人がいるときだけ（D21 R5）。"""
    return period.start.year not in ICHIJI_HALF_TEBIKI_YEARS and any(needs_rounding(x.ichiji) for x in after)  # type: ignore[attr-defined]


def _half_rounders(period: object, candidates: object, n: int) -> list:
    """一時所得の2分の1の丸めの関数（1人ずつ）。手引きの注記がある年分はその規則、それ以外は候補（_rounders）。"""
    rule = ICHIJI_HALF_TEBIKI_YEARS.get(period.start.year)  # type: ignore[attr-defined]
    if rule is not None:
        return [rule.apply] * n
    return _rounders(candidates, n)


def _listed_final(ls: Any) -> int:
    """繰越控除の後の配当所得等（損益通算の後の額から繰越控除の残りを引いた額）。"""
    return ls.dividend_final


def _no_rounding(x: object) -> int:
    raise AssertionError("端数が出ないはずの2分の1で丸めを使った")


def _rules2(p: object) -> Adjustment2Rules:
    return Adjustment2Rules(
        kyuyo_cap=int(p.給与所得控除後の給与等の金額の上限),  # type: ignore[attr-defined]
        nenkin_cap=int(p.公的年金等に係る雑所得の金額の上限),  # type: ignore[attr-defined]
        deduct=int(p.控除する額),  # type: ignore[attr-defined]
    )


def _rules1(p: object) -> Adjustment1Rules:
    r = p.第1項の率  # type: ignore[attr-defined]
    return Adjustment1Rules(int(p.第1項の給与等の収入金額の基準), int(p.第1項の給与等の収入金額の上限), int(r.分子), int(r.分母))  # type: ignore[attr-defined]


def _carryback_rules(p: object) -> CarrybackRules:
    rows = []
    for name in ("第1段", "第2段", "第3段", "第4段", "第5段", "第6段"):
        d = getattr(p.税率, name)  # type: ignore[attr-defined]
        rows.append((int(d.上限), Fraction(int(d.率.分子), int(d.率.分母))))
    top = p.税率.最高段.率  # type: ignore[attr-defined]
    rows.append((None, Fraction(int(top.分子), int(top.分母))))
    return CarrybackRules(int(p.課税標準の端数の単位), int(p.税額の端数の単位), tuple(rows))  # type: ignore[attr-defined]


def _offsets(rows: list[tuple[int, ...]]) -> list[AfterOffset]:
    """rows の各行：(配当, 不動産, 事業, 給与（調整控除の後）, 雑, 一時, 退職)。"""
    return [offset_losses(Incomes(*r)) for r in rows]


# ---------------------------------------------------------------------------
# 入力変数（式を持たない）
# ---------------------------------------------------------------------------


class 所得税_繰り越された純損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年以前3年内に生じ、まだ控除されていない純損失の金額（青色の年分のもの。提出した申告書の記載から作る：inputs.py）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.2"]


class 所得税_繰り越された雑損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年以前3年内に生じ、まだ控除されていない雑損失の金額（前年分の申告書の記載から作る：inputs.py）"
    reference = ["docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#8"]


class 所得税_繰り越された上場株式等の譲渡損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年以前3年内に生じ、まだ控除されていない上場株式等に係る譲渡損失の金額（前年分の申告書の記載から作る：inputs.py）"
    reference = [_KABU6]


class 所得税_一時所得の2分の1の端数の候補(Variable):
    value_type = str
    entity = 人物
    definition_period = YEAR
    label = "一時所得の金額の2分の1の1円未満の端数の処理の候補の名前（floor・ceil・half_up。evaluate が入れる。令和7年分は手引きの切捨てを使い、引かない）"
    reference = [
        "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md#11",
        "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#2",
    ]


class 所得税_上場株式等の譲渡損失の損益通算を適用するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る譲渡損失の損益通算（措法37の12の2①）の適用を受ける旨を記載するか（選択.株式等の申告 loss_offset）"
    reference = [_KABU6]


class 所得税_上場株式等の譲渡損失の繰越控除を適用するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "繰り越された上場株式等に係る譲渡損失の繰越控除（措法37の12の2⑤）を受けるか（選択.株式等の申告 carryforward）"
    reference = [_KABU6]


# ---------------------------------------------------------------------------
# 所得金額調整控除（第1項・第2項）
# ---------------------------------------------------------------------------


class 所得税_所得金額調整控除(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "所得金額調整控除の額（租税特別措置法第41条の3の11）。第1項（給与等の収入金額850万円超で特別障害者か、"
        "年齢23歳未満の扶養親族・特別障害者である同一生計配偶者又は扶養親族を有する者）と第2項の合計"
    )
    reference = [_GAPS, "docs/public-sources/20261109_round2_gaps-sources.md#3.5", "docs/measurements/20261109_round2_gaps-fetch-and-checks.md#C3"]

    def formula_2025_01_01(人, period, parameters):
        # 第2項の「給与所得控除後の給与等の金額」（同条第4項第5号。特定支出控除の前：kyuyo KY-11、2026-11-12。以前は 所得税_給与所得）
        給与 = 人("所得税_給与所得控除後の給与等の金額", period)
        年金 = 人("所得税_公的年金等に係る雑所得の金額", period)
        収入 = 人("所得税_給与等の収入金額", period)
        特別障害者 = 人("所得税_特別障害者に当たるか", period)
        有する = 人("所得税_所得金額調整控除の対象の親族等を有するか", period)
        p = parameters(period).所得税.所得金額調整控除
        rules2 = _rules2(p.第2項)
        rules1 = _rules1(p)
        return _out(
            [
                adjustment_1(w, bool(a) or bool(b), rules1) + adjustment_2(k, n, rules2)
                for (k, n, w), a, b in zip(_ints(給与, 年金, 収入), 特別障害者, 有する)
            ]
        )


# ---------------------------------------------------------------------------
# 合計所得金額とその仲間（繰越控除の前）
# ---------------------------------------------------------------------------


class 所得税_合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "合計所得金額（所得税法第2条第1項第30号イ(2)）。集約点。損益通算の後・繰越控除の前の総所得金額＋退職所得金額＋"
        "上場株式等に係る配当所得等（譲渡損失との損益通算の後）・譲渡所得等"
    )
    reference = [_R1, _GENKA, "docs/public-sources/20261109_round2b_kabu-law-and-nta.md#1.3", _KABU6]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 上場配当, 上場譲渡, 調整)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, _, _, adj in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            ls = listed(row[7], row[8], 0, offset=bool(o), carry=False)
            out.append(x.keijo + half_ichiji(x.ichiji, r) + x.taishoku + ls.dividend_offset + ls.gain)
        return _out(out)


class 所得税_所得金額調整控除の判定に使う合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "所得金額調整控除の第1項の控除の前の合計所得金額（第2項は当てる。ほかの人の第1項の判定に使う。循環を断つ値）"
    reference = [_GAPS, _R1]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        年金 = 人("所得税_公的年金等に係る雑所得の金額", period)
        控除後 = 人("所得税_給与所得控除後の給与等の金額", period)  # 第2項の「給与所得控除後の給与等の金額」（特定支出控除の前：kyuyo KY-11、2026-11-12）
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rules = _rules2(parameters(period).所得税.所得金額調整控除.第2項)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 上場配当, 上場譲渡, 年金, 控除後)
        after = _offsets([(a, b, c, d - adjustment_2(w, n, rules), e, f, g) for a, b, c, d, e, f, g, _, _, n, w in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            ls = listed(row[7], row[8], 0, offset=bool(o), carry=False)
            out.append(x.keijo + half_ichiji(x.ichiji, r) + x.taishoku + ls.dividend_offset + ls.gain)
        return _out(out)


class 所得税_公的年金等に係る雑所得以外の合計所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "公的年金等に係る雑所得以外の合計所得金額（所得税法第35条第4項）。雑所得は業務に係るものとその他のもの、"
        "所得金額調整控除の第2項は当てない（所基通35−8）"
    )
    reference = ["docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md#2.1", _GENKA]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
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


class 所得税_純損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "その年分に生じた純損失の金額（所得税法第2条第1項第25号：損益通算をしてもなお控除しきれない不動産所得・事業所得の損失）"
    reference = [_GENKA, "docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.1"]

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
        return _out([x.net_loss for x in after])


# ---------------------------------------------------------------------------
# 繰越控除（純損失・雑損失）とその後の総所得金額・退職所得金額
# ---------------------------------------------------------------------------


class 所得税_純損失の繰越控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "純損失の繰越控除の額（所得税法第70条、所令201①：損益通算の後、総所得金額から、次に退職所得金額から）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.2", "docs/public-sources/20261109_round2_genka-laws-and-nta.md#7"]

    def formula_2025_01_01(人, period, parameters):
        繰越 = 人("所得税_繰り越された純損失の金額", period)
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整, 繰越)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj, _ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        return _out(
            [apply_carryforwards(x.keijo + half_ichiji(x.ichiji, r), x.taishoku, row[8], 0).net for x, r, row in zip(after, rounders, rows)]
        )


class 所得税_雑損失の繰越控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = (
        "雑損失の繰越控除の額（所得税法第71条、所令204：損益通算・純損失の繰越控除の後、総所得金額、次に上場株式等の配当所得等・譲渡所得等"
        "（措令4の2⑨・25の11の2⑳）、次に退職所得金額から）"
    )
    reference = ["docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#8", _JOTO]

    def formula_2025_01_01(人, period, parameters):
        繰越 = 人("所得税_繰り越された雑損失の金額", period)
        純損失 = 人("所得税_純損失の繰越控除額", period)
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        上場繰越 = 人("所得税_上場株式等の譲渡損失の繰越控除額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整, 純損失, 繰越, 上場配当, 上場譲渡, 上場繰越)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj, *_ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            total = x.keijo + half_ichiji(x.ichiji, r)
            ls = listed(row[10], row[11], row[12], offset=bool(o), carry=True)
            out.append(split_casualty(total, x.taishoku, _listed_final(ls), ls.gain_final, row[8], row[9]).casualty)
        return _out(out)


class 所得税_総所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "総所得金額（所得税法第22条第2項：損益通算の後、一時所得は2分の1、純損失・雑損失の繰越控除の後）"
    reference = [_IRYOHI, _R1, _GENKA]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        純損失 = 人("所得税_純損失の繰越控除額", period)
        雑損失 = 人("所得税_雑損失の繰越控除額", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 調整, 純損失, 雑損失)
        after = _offsets([(a, b, c, d - adj, e, f, 0) for a, b, c, d, e, f, adj, _, _ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row in zip(after, rounders, rows):
            total = x.keijo + half_ichiji(x.ichiji, r)
            out.append(total - min(total, row[7] + row[8]))
        return _out(out)


class 所得税_退職所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "退職所得金額（所得税法第22条第3項：損益通算・純損失・雑損失の繰越控除の後の退職所得の金額）"
    reference = [_IRYOHI, _GENKA]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        純損失 = 人("所得税_純損失の繰越控除額", period)
        雑損失 = 人("所得税_雑損失の繰越控除額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        上場繰越 = 人("所得税_上場株式等の譲渡損失の繰越控除額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整, 純損失, 雑損失, 上場配当, 上場譲渡, 上場繰越)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj, *_ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            total = x.keijo + half_ichiji(x.ichiji, r)
            ls = listed(row[10], row[11], row[12], offset=bool(o), carry=True)
            sp = split_casualty(total, x.taishoku, _listed_final(ls), ls.gain_final, row[8], row[9])
            out.append(x.taishoku - (row[8] - min(total, row[8])) - sp.from_retirement)
        return _out(out)


# ---------------------------------------------------------------------------
# 上場株式等（申告分離課税）
# ---------------------------------------------------------------------------


class 所得税_上場株式等の譲渡損失の繰越控除額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る譲渡損失の繰越控除の額（措法37の12の2⑤：まず譲渡所得等から、次に損益通算の後の配当所得等から）"
    reference = [_KABU6]

    def formula_2025_01_01(人, period, parameters):
        繰越 = 人("所得税_繰り越された上場株式等の譲渡損失の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        適用 = 人("所得税_上場株式等の譲渡損失の繰越控除を適用するか", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        return _out(
            [
                listed(d, g, c, offset=bool(o), carry=bool(a)).carry
                for (d, g, c), o, a in zip(_ints(上場配当, 上場譲渡, 繰越), 通算, 適用)
            ]
        )


class 所得税_申告分離課税の上場株式等に係る配当所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る配当所得等の金額（措法8の4①。譲渡損失との損益通算・繰越控除の後：措法37の12の2①⑤）"
    reference = ["docs/public-sources/20261109_round2b_kabu-law-and-nta.md#1.1", _KABU6]

    def formula_2025_01_01(人, period, parameters):
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        繰越控除 = 人("所得税_上場株式等の譲渡損失の繰越控除額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        純損失 = 人("所得税_純損失の繰越控除額", period)
        雑損失 = 人("所得税_雑損失の繰越控除額", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整, 純損失, 雑損失, 上場配当, 上場譲渡, 繰越控除)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj, *_ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            total = x.keijo + half_ichiji(x.ichiji, r)
            ls = listed(row[10], row[11], row[12], offset=bool(o), carry=True)
            final = _listed_final(ls)
            sp = split_casualty(total, x.taishoku, final, ls.gain_final, row[8], row[9])
            out.append(final - sp.from_dividend)
        return _out(out)


class 所得税_申告分離課税の上場株式等に係る譲渡所得等の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "上場株式等に係る譲渡所得等の金額（措法37の11①。損失は0、繰越控除の後：措法37の12の2⑤）"
    reference = ["docs/public-sources/20261109_round2b_kabu-law-and-nta.md#4", _KABU6]

    def formula_2025_01_01(人, period, parameters):
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        繰越控除 = 人("所得税_上場株式等の譲渡損失の繰越控除額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        純損失 = 人("所得税_純損失の繰越控除額", period)
        雑損失 = 人("所得税_雑損失の繰越控除額", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 調整, 純損失, 雑損失, 上場配当, 上場譲渡, 繰越控除)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, adj, *_ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            total = x.keijo + half_ichiji(x.ichiji, r)
            ls = listed(row[10], row[11], row[12], offset=bool(o), carry=True)
            sp = split_casualty(total, x.taishoku, _listed_final(ls), ls.gain_final, row[8], row[9])
            out.append(ls.gain_final - sp.from_gain)
        return _out(out)


class 所得税_総所得金額等(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "総所得金額等（総所得金額＋退職所得金額＋申告分離課税の上場株式等の所得（繰越控除の後））"
    reference = [_IRYOHI, "docs/public-sources/20261109_impl-prep_iryohi-law-text.md#3.2", _KABU6]

    def formula_2025_01_01(人, period, parameters):
        配当 = 人("所得税_配当所得の金額", period)
        不動産 = 人("所得税_不動産所得の金額", period)
        事業 = 人("所得税_事業所得の金額", period)
        給与 = 人("所得税_給与所得", period)
        雑 = 人("所得税_雑所得の金額", period)
        一時 = 人("所得税_一時所得の金額", period)
        退職 = 人("所得税_退職所得の金額", period)
        上場配当 = 人("所得税_上場株式等に係る配当所得等の金額", period)
        上場譲渡 = 人("所得税_上場株式等に係る譲渡所得等の金額", period)
        調整 = 人("所得税_所得金額調整控除", period)
        純損失 = 人("所得税_純損失の繰越控除額", period)
        雑損失 = 人("所得税_雑損失の繰越控除額", period)
        上場繰越 = 人("所得税_上場株式等の譲渡損失の繰越控除額", period)
        通算 = 人("所得税_上場株式等の譲渡損失の損益通算を適用するか", period)
        rows = _ints(配当, 不動産, 事業, 給与, 雑, 一時, 退職, 上場配当, 上場譲渡, 調整, 純損失, 雑損失, 上場繰越)
        after = _offsets([(a, b, c, d - adj, e, f, g) for a, b, c, d, e, f, g, _, _, adj, _, _, _ in rows])
        候補 = 人("所得税_一時所得の2分の1の端数の候補", period) if _half_candidates_needed(period, after) else None
        rounders = _half_rounders(period, 候補, len(rows))
        out = []
        for x, r, row, o in zip(after, rounders, rows, 通算):
            total = x.keijo + half_ichiji(x.ichiji, r)
            ls = listed(row[7], row[8], row[12], offset=bool(o), carry=True)
            sp = split_casualty(total, x.taishoku, ls.dividend_final, ls.gain_final, row[10], row[11])
            out.append(total - min(total, row[10]) - sp.from_total + x.taishoku - (row[10] - min(total, row[10])) - sp.from_retirement + ls.dividend_final - sp.from_dividend + ls.gain_final - sp.from_gain)
        return _out(out)



class 所得税_前年分の課税総所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分の課税総所得金額（提出した前年分の申告書の記載：inputs.py）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_前年分の税額控除後の所得税の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分の所得税の額（税額控除の後。繰戻しの還付の限度）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_前年分の課税退職所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分の課税退職所得金額（提出した前年分の申告書の記載 taxable_retirement_income。繰り戻す額が課税総所得金額を超えるときの控除先：所令271①三）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_前年分の課税山林所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分の課税山林所得金額（提出した前年分の申告書の記載 taxable_timber_income。山林所得は範囲外：正なら checks.py が対象外にする）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_前年分の課税退職所得金額等の記載があるか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "前年分の申告書に課税退職所得金額・課税山林所得金額の両方の記載（0 を含む）があるか"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_前年分に青色申告書を提出したか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "前年分の所得税につき青色申告書を提出しているか（前年分の申告書と青色申告の承認の通知の記録：inputs.py）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_繰り戻す純損失の金額の選択(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分に繰り戻す純損失の金額（選択.損失申告と繰戻し。全額の候補は int の上限の値で、式で純損失の金額に切り詰める）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_その年分の確定申告書を期限内に提出するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "その年分の青色申告書を提出期限までに提出するか（計画.申告の方法と時期 の within_deadline）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3"]


class 所得税_純損失の繰戻しによる還付請求額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "純損失の繰戻しによる還付請求額（所得税法第140条・第141条、所令271①一・三：課税総所得金額、次に課税退職所得金額から控除）"
    reference = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3", "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#9"]

    def formula_2025_01_01(人, period, parameters):
        純損失 = 人("所得税_純損失の金額", period)
        青色 = 人("所得税_青色申告の承認を受けているか", period)
        前年課税 = 人("所得税_前年分の課税総所得金額", period)
        前年税額 = 人("所得税_前年分の税額控除後の所得税の額", period)
        前年青色 = 人("所得税_前年分に青色申告書を提出したか", period)
        繰戻し = 人("所得税_繰り戻す純損失の金額の選択", period)
        期限内 = 人("所得税_その年分の確定申告書を期限内に提出するか", period)
        前年退職 = 人("所得税_前年分の課税退職所得金額", period)
        rules = _carryback_rules(parameters(period).所得税.純損失の繰戻し)
        out = []
        for (nl, prev, cap, chosen, ret), b, pb, t in zip(_ints(純損失, 前年課税, 前年税額, 繰戻し, 前年退職), 青色, 前年青色, 期限内):
            out.append(carryback_refund(prev, min(chosen, nl), cap, rules, ret) if b and pb and t and chosen > 0 and nl > 0 else 0)
        return _out(out)



_SECOND = ["docs/public-sources/20261109_round2_aoiro-laws-and-nta.md#5.3", "docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md#9"]


class 所得税_前々年分に繰り戻す純損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前々年分に繰り戻す純損失の金額（所法140⑤・141④：その年の前年の純損失の残りが限度。選択.損失申告と繰戻し の second_prior_year_carryback_amount）"
    reference = _SECOND


class 所得税_前々年分の課税総所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前々年分の課税総所得金額（提出した前々年分の申告書の記載：所令272②）"
    reference = _SECOND


class 所得税_前々年分の課税退職所得金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前々年分の課税退職所得金額（提出した前々年分の申告書の記載：所令272②・271①三）"
    reference = _SECOND


class 所得税_前々年分の税額控除後の所得税の額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前々年分の所得税の額（税額控除の後。前々年分への繰戻しの還付の限度：所令272②・所法140②）"
    reference = _SECOND


class 所得税_前々年分に既に繰り戻した純損失の金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前年分の申告で前々年分に繰り戻した（所法140①・141①）前年の純損失の金額（前年分の申告書の net_loss_carryback：所令272② 後段）"
    reference = _SECOND


class 所得税_前々年分への純損失の繰戻しによる還付請求額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "事業の全部の譲渡・廃止等（所法140⑤・所令272①）又は死亡（所法141④）の年の前年の純損失を前々年分に繰り戻す還付の請求額（所令272②）"
    reference = _SECOND

    def formula_2025_01_01(人, period, parameters):
        繰戻し = 人("所得税_前々年分に繰り戻す純損失の金額", period)
        課税 = 人("所得税_前々年分の課税総所得金額", period)
        退職 = 人("所得税_前々年分の課税退職所得金額", period)
        税額 = 人("所得税_前々年分の税額控除後の所得税の額", period)
        既に = 人("所得税_前々年分に既に繰り戻した純損失の金額", period)
        # 所法89① の表は令和5年分〜令和8年分で同文（docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §2、
        # docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §2）。前々年分（令和5年分・令和6年分）の表は同じパラメータの値
        rules = _carryback_rules(parameters(period).所得税.純損失の繰戻し)
        out = []
        for back, taxable, ret, cap, prior in _ints(繰戻し, 課税, 退職, 税額, 既に):
            out.append(second_prior_refund(taxable, back, cap, rules, ret, prior) if back > 0 else 0)
        return _out(out)

#: 損益通算をする式の変数（不動産所得の損失の扱いが決まらないときに checks.py が対象外にする）。
OFFSET_VARIABLES: tuple[str, ...] = (
    "所得税_合計所得金額",
    "所得税_所得金額調整控除の判定に使う合計所得金額",
    "所得税_公的年金等に係る雑所得以外の合計所得金額",
    "所得税_純損失の金額",
    "所得税_純損失の繰越控除額",
    "所得税_雑損失の繰越控除額",
    "所得税_総所得金額",
    "所得税_退職所得金額",
    "所得税_総所得金額等",
)

VARIABLES = (
    所得税_繰り越された純損失の金額,
    所得税_繰り越された雑損失の金額,
    所得税_繰り越された上場株式等の譲渡損失の金額,
    所得税_一時所得の2分の1の端数の候補,
    所得税_上場株式等の譲渡損失の損益通算を適用するか,
    所得税_上場株式等の譲渡損失の繰越控除を適用するか,
    所得税_所得金額調整控除,
    所得税_合計所得金額,
    所得税_所得金額調整控除の判定に使う合計所得金額,
    所得税_公的年金等に係る雑所得以外の合計所得金額,
    所得税_純損失の金額,
    所得税_純損失の繰越控除額,
    所得税_雑損失の繰越控除額,
    所得税_総所得金額,
    所得税_退職所得金額,
    所得税_上場株式等の譲渡損失の繰越控除額,
    所得税_申告分離課税の上場株式等に係る配当所得等の金額,
    所得税_申告分離課税の上場株式等に係る譲渡所得等の金額,
    所得税_総所得金額等,
    所得税_前年分の課税総所得金額,
    所得税_前年分の税額控除後の所得税の額,
    所得税_前年分の課税退職所得金額,
    所得税_前年分の課税山林所得金額,
    所得税_前年分の課税退職所得金額等の記載があるか,
    所得税_前年分に青色申告書を提出したか,
    所得税_繰り戻す純損失の金額の選択,
    所得税_その年分の確定申告書を期限内に提出するか,
    所得税_純損失の繰戻しによる還付請求額,
    所得税_前々年分に繰り戻す純損失の金額,
    所得税_前々年分の課税総所得金額,
    所得税_前々年分の課税退職所得金額,
    所得税_前々年分の税額控除後の所得税の額,
    所得税_前々年分に既に繰り戻した純損失の金額,
    所得税_前々年分への純損失の繰戻しによる還付請求額,
)

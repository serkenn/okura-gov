"""規則モジュール income_totals の純粋関数（1人分。整数の円と Fraction だけ。float は使わない）。

- 所得金額調整控除の第1項（措法41の3の11①）と第2項（同条②）
- 損益通算（所法69①、所令198 第1号・第3号・第5号）：不動産所得・事業所得の損失を、経常所得 → 一時所得 → 退職所得 の順に控除する。
  総合課税の譲渡所得・山林所得は範囲外（入力にあれば income_kinds が対象外にする：D20・D21 R3）。
- 一時所得の2分の1（所法22②二）：1円未満の端数の定めがないので、端数の候補の関数を受け取る（D22 S3）。
- 純損失・雑損失の繰越控除（所法70・71、所令201①二・204①②）：損益通算の後、純損失を先に、総所得金額 → 退職所得金額 の順。
  雑損失は措令4の2⑨・25の11の2⑳ の読替えで、総所得金額 → 上場株式等に係る配当所得等 → 上場株式等に係る譲渡所得等 → 退職所得金額（上場分は損益通算・繰越控除の後）の順。
- 上場株式等の譲渡損失の損益通算と繰越控除（措法37の12の2①⑤、措令25の11の2⑧二）。

所得の種類ごとの所得（income_kinds）は、損失を負の値で受け取る前提。配当所得・雑所得・一時所得の損失は他の所得から控除しない
（所法69① の対象でない：TA No.2250（注2）、docs/public-sources/20261109_round2_genka-laws-and-nta.md §6.3）ので0として扱う。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction

from ...basis import SourceKind
from ...rounding import RoundingRule, floor_to_unit

Rounder = Callable[[int | Fraction], int]

#: 令和7年分の一時所得の2分の1の1円未満の切捨て（法令・通達に定めは見つからず、手引きの注記に従う：D21 R5・D22 S2）。
ICHIJI_HALF_TEBIKI_R7 = RoundingRule(
    name="floor_yen_ichiji_half_tebiki_r7",
    title="令和7年分の総所得金額に入れる一時所得の金額の2分の1の1円未満の端数を切り捨てる（令和8年分は手引きが未公表で候補で評価する）",
    function="floor",
    source_kind=SourceKind.GUIDE_OR_FORM_NOTE,
    law=(
        "令和7年分 所得税及び復興特別所得税の確定申告の手引き 第一表⑪「総合譲渡・一時」の計算欄"
        "（H＝（B＋G）×0.5「1円未満の端数があるときは、その端数を切り捨てます。」）。所得税法第22条第2項第2号と通達に端数の定めは見つからない"
    ),
    references=(
        "docs/public-sources/20261109_round2_yoshiki-forms-r07.md#2",
        "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md#6",
    ),
)

#: 所得金額調整控除の第1項の1円未満の切上げ（条文に端数の定めはなく、国税庁の説明に従う：D21 R5・D22 S2）。
ADJUSTMENT_1_CEIL = RoundingRule(
    name="ceil_yen_adjustment_1_ta1411",
    title="所得金額調整控除の第1項の控除額の1円未満の端数を切り上げる（国税庁の説明）",
    function="ceil",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="TA No.1411「1円未満の端数があるときは、その端数を切り上げます。」（租税特別措置法第41条の3の11第1項に端数の定めはない）",
    references=("docs/public-sources/20261109_round2_gaps-sources.md#3.5",),
)

#: 手引きの注記で一時所得の2分の1の1円未満を決められる年分（それ以外の年分は候補の全部で評価する。令和8年分の手引きは未公表）。
ICHIJI_HALF_TEBIKI_YEARS: Mapping[int, RoundingRule] = {2025: ICHIJI_HALF_TEBIKI_R7}


def _yen(x: object, what: str) -> int:
    if type(x) is not int:
        raise TypeError(f"{what}は整数の円（{type(x).__name__} が来た）")
    return x


# ---------------------------------------------------------------------------
# 所得金額調整控除（第2項）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Adjustment2Rules:
    """第2項のパラメータ（所得税.所得金額調整控除.第2項）。"""

    kyuyo_cap: int
    nenkin_cap: int
    deduct: int


@dataclass(frozen=True)
class Adjustment1Rules:
    """第1項のパラメータ（所得税.所得金額調整控除.第1項の…）。率は numerator/denominator。"""

    base: int
    top: int
    numerator: int
    denominator: int


def adjustment_1(wages: int, qualifies: bool, rules: Adjustment1Rules) -> int:
    """第1項の控除額：（給与等の収入金額（1,000万円を超えるときは1,000万円）− 850万円）× 10/100（1円未満切上げ：TA No.1411）。

    850万円以下・要件を満たさない人は0（措法41の3の11①）。計算例（docs/public-sources/20261109_round2_gaps-sources.md §3.5、
    docs/inferences/20261109_round2_gaps-inferences.md IG3）：収入 9,000,000 → 50,000、9,500,000 → 100,000、10,000,000 超 → 150,000、8,500,001 → 1（切上げ）。
    """
    w = _yen(wages, "給与等の収入金額")
    if not qualifies or w <= rules.base:
        return 0
    amount = Fraction((min(w, rules.top) - rules.base) * rules.numerator, rules.denominator)
    return ADJUSTMENT_1_CEIL.apply(amount)


def adjustment_2(kyuyo_after_deduction: int, nenkin_zatsu: int, rules: Adjustment2Rules) -> int:
    """第2項の控除額。給与所得控除後の給与等の金額と公的年金等に係る雑所得の金額の両方がある居住者だけ。

    給与所得控除後の給与等の金額は措法41の3の11④五の額（収入金額−給与所得控除額。別表第五・措法29の4② を含む）で、特定支出控除の前
    （kyuyo の 所得税_給与所得控除後の給与等の金額。2026-11-12、kyuyo の KY-11：以前は 所得税_給与所得 を渡していた）。

    {min(給与所得控除後の給与等の金額, 10万円) + min(公的年金等に係る雑所得の金額, 10万円)} − 10万円（合計額が10万円を超えるとき）。
    実測 C3 の計算例：50,000・40,000 → 0、50,000・80,000 → 30,000、200,000・300,000 → 100,000、100,000・1 → 1、0・500,000 → 0。
    """
    k = _yen(kyuyo_after_deduction, "給与所得控除後の給与等の金額")
    n = _yen(nenkin_zatsu, "公的年金等に係る雑所得の金額")
    if k <= 0 or n <= 0:
        return 0
    return max(0, min(k, rules.kyuyo_cap) + min(n, rules.nenkin_cap) - rules.deduct)


# ---------------------------------------------------------------------------
# 損益通算
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Incomes:
    """所得の種類ごとの所得の金額（損益通算の前）。kyuyo は所得金額調整控除の後（措令26の5①）。"""

    haito: int
    fudosan: int
    jigyo: int
    kyuyo: int
    zatsu: int
    ichiji: int
    taishoku: int = 0

    def __post_init__(self) -> None:
        for name in ("haito", "fudosan", "jigyo", "kyuyo", "zatsu", "ichiji", "taishoku"):
            _yen(getattr(self, name), name)
        # 2026-11-12（kyuyo の KY-11、kyuyo の担当が直した）：給与所得の金額から所得金額調整控除の第2項（特定支出控除の前の給与所得控除後の給与等の金額で
        # 計算する）を引くと負になりうる。負の給与所得は損益通算しない（offset_losses が0にする）。以前は kyuyo も負を誤りにしていた
        if self.taishoku < 0:
            raise ValueError("退職所得の金額は負にならない")


@dataclass(frozen=True)
class AfterOffset:
    """損益通算の後の金額（どれも0以上）。ichiji は2分の1にする前。"""

    keijo: int  # 経常所得の金額の合計（利子・配当・不動産・事業・給与・雑）
    ichiji: int
    taishoku: int
    net_loss: int  # 純損失の金額（所法2①二十五）


def offset_losses(inc: Incomes) -> AfterOffset:
    """所令198：不動産所得・事業所得の損失は、まず経常所得から（一号）、なお控除しきれない額を一時所得から（三号。総合課税の
    譲渡所得は範囲外）、次に退職所得から（五号。山林所得は範囲外）控除する。残りが純損失の金額（所法2①二十五）。

    経常所得の中では、不動産所得・事業所得の黒字と赤字を合わせる（「他の…経常所得の金額から控除する」）。配当所得・雑所得の
    損失は0とする（所法69① の対象外）。計算例：事業 −500,000、給与 300,000、雑 100,000、一時 200,000 → 経常 0・一時 100,000
    （実測 docs/measurements/20261109_round2_genka-fetch-and-checks.md §5.4 E6）。
    """
    # 給与所得の金額（所得金額調整控除の後）も所法69① の損失でないので0未満にしない（特定支出控除〔所法57の2〕で給与所得の金額が所得金額調整控除の
    # 額より小さくなる人がいる：rules/kyuyo の KY-11、2026-11-12 に kyuyo の担当が足した。以前は給与所得が0未満にならず、この行は inc.kyuyo のままだった）
    keijo = max(inc.haito, 0) + inc.fudosan + inc.jigyo + max(inc.kyuyo, 0) + max(inc.zatsu, 0)
    ichiji = max(inc.ichiji, 0)
    taishoku = inc.taishoku
    if keijo >= 0:
        return AfterOffset(keijo, ichiji, taishoku, 0)
    loss = -keijo
    d = min(loss, ichiji)
    ichiji, loss = ichiji - d, loss - d
    d = min(loss, taishoku)
    taishoku, loss = taishoku - d, loss - d
    return AfterOffset(0, ichiji, taishoku, loss)


def half_ichiji(ichiji: int, rounder: Rounder) -> int:
    """総所得金額に入れる一時所得の金額の2分の1（所法22②二）。条文に1円未満の端数の定めがなく（docs/public-sources/
    20261109_impl-prep_jigyo-laws-and-nta.md §11「所法22 には「端数」の語がない」）、呼ぶ側が丸めの関数を渡す
    （令和7年分は手引きの切捨て ICHIJI_HALF_TEBIKI_R7、手引きのない年分は候補の関数：D21 R5・D22 S3）。"""
    if ichiji < 0:
        raise ValueError("損益通算の後の一時所得の金額は0以上")
    if ichiji % 2 == 0:
        return ichiji // 2
    return rounder(Fraction(ichiji, 2))


def needs_rounding(ichiji: int) -> bool:
    return ichiji % 2 != 0


# ---------------------------------------------------------------------------
# 純損失・雑損失の繰越控除
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CasualtySplit:
    """雑損失の繰越控除の、控除する所得ごとの額（措令4の2⑨・25の11の2⑳：総所得金額→上場配当→上場譲渡→退職）。"""

    casualty: int  # 控除する雑損失の合計
    from_total: int  # 総所得金額（純損失の控除の後）から
    from_dividend: int
    from_gain: int
    from_retirement: int


def split_casualty(total_before: int, retirement_before: int, dividend: int, gain: int, net_used: int, casualty_carried: int) -> CasualtySplit:
    """純損失の繰越控除（net_used。総所得金額 → 退職所得金額の順で控除した額）の後の金額から、雑損失を順に控除する（所令204②・措令25の11の2⑳）。

    純損失は上場分に及ばない（所法70 は措法8の4③三・37の10⑥五の読替えの対象外）。dividend・gain は損益通算・繰越控除の後の上場分（措令25の11の2⑰⑱）。
    計算例：総所得 0・配当 100万・譲渡 100万・雑損失 150万 → 配当 100万・譲渡 50万（docs/inferences/20261111_impl-research_joto-junjo-cases.md I2）。
    """
    for x, what in ((total_before, "総所得金額"), (retirement_before, "退職所得金額"), (dividend, "上場配当"), (gain, "上場譲渡"), (net_used, "純損失の控除"), (casualty_carried, "雑損失")):
        if _yen(x, what) < 0:
            raise ValueError(f"{what}は0以上")
    from_total_net = min(total_before, net_used)
    total_left = total_before - from_total_net
    retirement_left = retirement_before - (net_used - from_total_net)
    base = total_left + dividend + gain + retirement_left
    casualty = min(casualty_carried, base)
    rest = casualty
    a = min(rest, total_left)
    rest -= a
    b = min(rest, dividend)
    rest -= b
    c = min(rest, gain)
    rest -= c
    d = rest
    return CasualtySplit(casualty, a, b, c, d)


@dataclass(frozen=True)
class Carryforward:
    """繰越控除の結果。net・casualty は控除した額、total_income・retirement は控除の後の総所得金額・退職所得金額。"""

    net: int
    casualty: int
    total_income: int
    retirement: int


def apply_carryforwards(total_before: int, retirement_before: int, net_carried: int, casualty_carried: int) -> Carryforward:
    """所令201①二・204①二②：損益通算の後、純損失を先に、雑損失を後に控除する。どちらも総所得金額から、控除しきれない額を
    退職所得金額から（山林所得は範囲外）。計算例：前年の純損失 1,000,000、総所得金額 600,000 → 600,000 を控除
    （実測 docs/measurements/20261109_round2_aoiro-fetch-and-checks.md §4.3 C1）。雑損失 800,000（古い年から）、総所得 300,000・
    退職 100,000 → 400,000 を控除（実測 docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md §4 [7]）。
    """
    for x, what in ((total_before, "総所得金額"), (retirement_before, "退職所得金額"), (net_carried, "純損失"), (casualty_carried, "雑損失")):
        if _yen(x, what) < 0:
            raise ValueError(f"{what}は0以上")
    base = total_before + retirement_before
    net = min(net_carried, base)
    casualty = min(casualty_carried, base - net)
    from_total = min(total_before, net + casualty)
    from_retirement = net + casualty - from_total
    return Carryforward(net, casualty, total_before - from_total, retirement_before - from_retirement)


# ---------------------------------------------------------------------------
# 上場株式等
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Listed:
    """上場株式等の所得。dividend_offset は譲渡損失との損益通算の後の配当所得等（繰越控除の前。合計所得金額に入る）、
    gain は譲渡所得等（損失は0：措法37の11①後段）、carry は繰越控除の額、dividend_final・gain_final は繰越控除の後。"""

    dividend_offset: int
    gain: int
    carry: int
    dividend_final: int
    gain_final: int


def listed(dividend: int, gain_or_loss: int, carried: int, *, offset: bool, carry: bool) -> Listed:
    """措法37の12の2：①譲渡損失を申告分離課税の配当所得等の限度で控除（offset＝適用の記載）。⑤繰り越された譲渡損失を
    まず譲渡所得等から、次に配当所得等から控除（措令25の11の2⑧二。carry＝明細書の添付）。
    計算例（実測 docs/measurements/20261109_round2b_kabu-fetch-and-verify.md §6）：S3 譲渡損 300,000・配当 100,000 → 配当 0。
    S4 繰越損失 400,000・譲渡益 300,000・配当 200,000 → 合計所得金額に入る額 500,000、繰越控除の後 100,000。
    """
    _yen(dividend, "配当所得等の金額")
    _yen(gain_or_loss, "譲渡所得等の金額")
    if _yen(carried, "繰り越された譲渡損失") < 0:
        raise ValueError("繰り越された譲渡損失は0以上")
    d = max(dividend, 0)
    g = max(gain_or_loss, 0)
    loss = max(-gain_or_loss, 0)
    if offset:
        d -= min(d, loss)
    c = min(carried, g + d) if carry else 0
    from_gain = min(c, g)
    from_dividend = c - from_gain
    return Listed(d, g, c, d - from_dividend, g - from_gain)


# ---------------------------------------------------------------------------
# 純損失の繰戻しによる還付（所法140①②④・141①〜③、所令271①一、所基通140・141−2・−4）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CarrybackRules:
    """繰戻しの還付の計算のパラメータ（所得税.純損失の繰戻し）。brackets は (上限, 率) を低い段から。最高段の上限は None。"""

    base_unit: int
    tax_unit: int
    brackets: tuple[tuple[int | None, Fraction], ...]


def _raw_income_tax(amount: int, rules: CarrybackRules) -> Fraction:
    """所法89① の超過累進の税額（端数処理の前）。課税標準は千円未満を切り捨てる（所基通140・141−4 が準用する通則法118①）。"""
    x = floor_to_unit(amount, rules.base_unit)
    total: Fraction = Fraction(0)
    lower = 0
    for upper, rate in rules.brackets:
        top = x if upper is None else min(x, upper)
        if top > lower:
            total += (top - lower) * rate
        if upper is None or x <= upper:
            break
        lower = upper
    return total


def _income_tax(amount: int, rules: CarrybackRules, retirement: int = 0) -> int:
    """所法140① 各号の所得税の額：課税総所得金額と課税退職所得金額のそれぞれに所法89① を当てた額の合計。百円未満を切り捨てる（所基通140・141−4 が準用する
    通則法119①。様式の ⑬・㉑ は合計で「100円未満の端数切捨て」）。"""
    return floor_to_unit(_raw_income_tax(amount, rules) + _raw_income_tax(retirement, rules), rules.tax_unit)


def carryback_refund(prev_taxable: int, carried: int, after_credits: int, rules: CarrybackRules, prev_retirement: int = 0) -> int:
    """前年分の税額 − 繰り戻した後の税額（前年分の税額控除後の所得税の額が限度：所法140②、所基通140・141−2）。

    繰り戻す純損失（総所得金額の計算上生じた損失）は、まず前年分の課税総所得金額から、控除しきれない部分は課税山林所得金額、次に課税退職所得金額から
    控除する（所令271①一・三）。課税山林所得金額は範囲外（D20）で、それがある人は呼ぶ側（checks.py）が対象外にするので、ここでは0とする。
    計算例：docs/measurements/20261109_round2_aoiro-fetch-and-checks.md §4.3 K1（前年の課税総所得金額 300万円、純損失 100万円 →
    202,500 − 102,500 ＝ 100,000）、K3（限度 50,000）。docs/measurements/20261109_round3_shibo-shukkoku-fetch-and-calc.md §4 [6]
    （400万円、150万円 → 220,000）。
    """
    if min(prev_taxable, carried, after_credits, prev_retirement) < 0:
        raise ValueError("繰戻しの基礎は0以上の整数の円")
    from_total = min(carried, prev_taxable)
    from_retirement = min(carried - from_total, prev_retirement)
    before = _income_tax(prev_taxable, rules, prev_retirement)
    after = _income_tax(prev_taxable - from_total, rules, prev_retirement - from_retirement)
    return min(max(before - after, 0), after_credits)


def second_prior_refund(
    prev2_taxable: int, carried: int, prev2_after_credits: int, rules: CarrybackRules, prev2_retirement: int = 0, prior_carryback: int = 0
) -> int:
    """事業の全部の譲渡・廃止等（所法140⑤・所令272①）又は死亡（所法141④）の年の前年の純損失を前々年分に繰り戻す還付請求額（所令272②）。

    前々年分の課税総所得金額・課税退職所得金額と所得税の額を基礎に、所法140①〜③・所令271 に準じて計算する（carryback_refund と同じ）。
    既に前々年分に所法140①・141① の繰戻し（前年分の申告書の net_loss_carryback）があったときは、前々年分の課税総所得金額等から
    その純損失の金額を控除した金額（所令271 の順：課税総所得金額、次に課税退職所得金額）を課税総所得金額等とみなし、
    所得税の額からその繰戻しで還付された金額を控除した金額を所得税の額とみなす（所令272② 後段）。
    「所得税の額」を還付の限度（所法140②：税額控除後の所得税の額。所基通140・141−2）と読み、各号の所得税の額は控除した後の課税総所得金額等から
    計算する（法令の読み。前の還付が限度で止まっていなければ、各号の所得税の額から還付額を引く読みと同じ値になる）。
    出典：docs/public-sources/20261109_round2_aoiro-laws-and-nta.md §5.3、docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §9、
    所令272② の本文 scripts/results/R2X_aoiro_laws/shotoku-rei_<asof>.txt。
    """
    if min(prev2_taxable, carried, prev2_after_credits, prev2_retirement, prior_carryback) < 0:
        raise ValueError("繰戻しの基礎は0以上の整数の円")
    refunded = carryback_refund(prev2_taxable, prior_carryback, prev2_after_credits, rules, prev2_retirement)
    from_total = min(prior_carryback, prev2_taxable)
    from_retirement = min(prior_carryback - from_total, prev2_retirement)
    return carryback_refund(
        prev2_taxable - from_total, carried, prev2_after_credits - refunded, rules, prev2_retirement - from_retirement
    )

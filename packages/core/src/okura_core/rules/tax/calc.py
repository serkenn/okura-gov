"""規則モジュール tax の純粋関数（OpenFisca の式・計算の後の検出・根拠の組み立てが共通に使う。規則の置き場所は1か所）。

金額は整数の円、途中の値は Fraction（float は使わない）。パラメータは OpenFisca の ParameterNodeAtInstant（追跡つきでもよい）から読む。

- 所得控除の当て方（所得税法第87条第2項、租税特別措置法第8条の4第3項第3号・第37条の11第6項の読替え）：allocate_deductions
- 超過累進税率（所得税法第89条第1項）：progressive_tax
- 税額控除の差引（第一表 ㊷。手引き 3-4_36 の順、赤字は0）：deduct_credits（2026-11-12）
- 精算（申告納税額・第3期分・還付。手引きの順と国税通則法第119条・第120条、復興財源確保法第24条）：settle
- 申告の要否（所得税法第120条第1項・第121条）：filing_obligation
- 期限（所得税法第120条第1項・第125条第1項、国税通則法第10条、祝日法第2条・第3条、暦要項、通達）：normal_deadline・death_deadline
根拠は docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md・20261109_round3_shibo-shukkoku-laws-and-nta.md・
20261109_round2b_kabu-law-and-nta.md（各関数の説明）。
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...rounding import RoundingRule, floor_to_unit

# ---------------------------------------------------------------------------
# 端数（単位つきの切捨て）と、根拠のある1円未満の端数
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitFloor:
    """単位（千円・百円）未満を切り捨てる名前つきの端数処理。単位の値はパラメータ（法令の値）から渡す。

    共有の rounding.RoundingRule は1円未満の関数だけを持つので、単位つきの切捨てをこのモジュールで名前つきにする。
    """

    name: str
    title: str
    parameter: str
    law: str
    references: tuple[str, ...]
    source_kind: SourceKind = SourceKind.LAW
    flags: tuple[ReadingFlag, ...] = ()

    def apply(self, x: int | Fraction, unit: int) -> int:
        if type(unit) is not int or unit <= 0:
            raise TypeError(f"{self.parameter} は1以上の整数が必要")
        return floor_to_unit(x, unit)

    def basis_entry(self) -> BasisEntry:
        return BasisEntry(
            type=BasisType.ROUNDING,
            name=self.name,
            source_kind=self.source_kind,
            references=self.references,
            flags=self.flags,
            law=self.law,
            detail={"function": "floor_to_unit", "title": self.title, "unit_parameter": self.parameter},
        )


P_KAZEI_UNIT = "所得税.端数計算.課税標準の単位"
P_KAKUTEI_UNIT = "所得税.端数計算.確定金額の単位"

#: 課税標準の千円未満の切捨て（全額が千円未満なら0）。
KAZEI_HYOJUN_FLOOR = UnitFloor(
    name="floor_kazei_hyojun_sen_en",
    title="課税標準（課税総所得金額・課税退職所得金額・上場株式等の課税所得）の千円未満の端数を切り捨てる（全額が千円未満なら0）",
    parameter=P_KAZEI_UNIT,
    law="国税通則法第118条第1項",
    references=(
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#1.2",
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#1.3",
    ),
)

#: 所得税と復興特別所得税の確定金額の合計額の百円未満の切捨て。
KAKUTEI_KINGAKU_FLOOR = UnitFloor(
    name="floor_kakutei_kingaku_hyaku_en",
    title="所得税と復興特別所得税の確定金額の合計額（申告納税額・第3期分の税額の黒字）の百円未満の端数を切り捨てる（全額が百円未満なら0）",
    parameter=P_KAKUTEI_UNIT,
    law="国税通則法第119条第1項、復興財源確保法第24条第2項（合計額で端数計算）。申告納税額と第3期分の両方で切り捨てる順序は手引き ㊿・52",
    references=(
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#1.2",
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#3.1",
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#3.3",
    ),
)

#: 令和7年分の復興特別所得税額の1円未満の切捨て（法令の規定は見つからず、手引きの注記に従う：D21 R5）。
FUKKO_TEBIKI_FLOOR_R7 = RoundingRule(
    name="floor_yen_fukko_tokubetsu_shotokuzei_tebiki_r7",
    title="令和7年分の復興特別所得税額（基準所得税額×2.1%）の1円未満の端数を切り捨てる",
    function="floor",
    source_kind=SourceKind.GUIDE_OR_FORM_NOTE,
    law=(
        "令和7年分 所得税及び復興特別所得税の確定申告の手引き p.27 第一表㊺の注（「1円未満の端数があるときは、その端数を切り捨てます。」）。"
        "復興財源確保法第13条・第24条、復興特別所得税に関する政令・省令に規定は見つからない"
    ),
    references=(
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#3.3",
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#10",
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#11",
    ),
)

#: 令和8年分の復興特別所得税額の1円未満の切捨て（手引きは未公表。国税通則法基本通達の一般の定めに従う読み：D22 S1・hasu H3）。
FUKKO_TSUTATSU_FLOOR_R8 = RoundingRule(
    name="floor_yen_fukko_tokubetsu_shotokuzei_tsutatsu_r8",
    title="令和8年分の復興特別所得税額（基準所得税額×2.1%）の1円未満の端数を切り捨てる",
    function="floor",
    source_kind=SourceKind.CIRCULAR,
    law=(
        "国税通則法基本通達（徴収部関係）第119条関係6（「国税の確定金額を算出する過程におけるその算出額に、1円未満の端数があるときは、"
        "その端数金額を切り捨てるものとする」）。復興特別所得税額に当てるのは法令の読み（令和8年分の手引きが公表されたら照合する）"
    ),
    references=(
        "docs/public-sources/20261111_impl-research_hasu-tebiki-and-nta.md#5",
        "docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md#3.3",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
)

#: 1円未満の根拠がある年分（手引きの注記・通達の読み）。ここにない年分は候補の全部で評価する。
FUKKO_ROUNDING_YEARS: Mapping[int, RoundingRule] = {2025: FUKKO_TEBIKI_FLOOR_R7, 2026: FUKKO_TSUTATSU_FLOOR_R8}


def _int(v: Any, name: str) -> int:
    if type(v) is not int:
        raise TypeError(f"パラメータ {name} は整数が必要（{type(v).__name__}）")
    return v


def rate_of(node: Any, name: str) -> Fraction:
    """率.分子・率.分母（または分子・分母）の節から Fraction を作る。"""
    num = _int(node.分子, f"{name}.分子")
    den = _int(node.分母, f"{name}.分母")
    if den <= 0:
        raise ValueError(f"{name} の分母が0以下")
    return Fraction(num, den)


# ---------------------------------------------------------------------------
# 所得控除の当て方（所得税法第87条第2項と措置法の読替え）
# ---------------------------------------------------------------------------


#: 所得控除を上場株式等に係る所得に当てる順序（措通31・32共−4：通達の順と、ただし書の納税者の選択）。
ORDER_TSUTATSU = "配当所得等→譲渡所得等"
ORDER_ALT = "譲渡所得等→配当所得等"
ORDERS = (ORDER_TSUTATSU, ORDER_ALT)


@dataclass(frozen=True)
class Allocation:
    """所得控除を当てた後の課税標準（千円未満切捨て後）。stock_order_matters は上場株式等の2つの順序で結果が違うか。"""

    総所得: int
    配当: int
    譲渡: int
    退職: int
    stock_order_matters: bool


def allocate_deductions(総所得: int, 配当: int, 譲渡: int, 退職: int, 控除: int, unit: int, order: str = ORDER_TSUTATSU) -> Allocation:
    """所得控除の合計を、総所得金額 → 上場株式等に係る配当所得等・譲渡所得等 → 山林所得金額（範囲外：0）→ 退職所得金額の順に当てる。

    - 所得税法第87条第2項：総所得金額、山林所得金額又は退職所得金額から順次控除（zeigaku §1.1）。
    - 措法第8条の4第3項第3号・第37条の10第6項第5号（第37条の11第6項で準用）：第87条の「総所得金額」を「総所得金額、上場株式等に係る
      配当所得等の金額」「総所得金額、…上場株式等に係る譲渡所得等の金額」と読み替える（kabu §1.3・§4）。
    - 配当所得等と譲渡所得等の間の順序：措通31・32共−4（通達）は ①総所得金額 →（⑧上場株式等に係る配当所得等 → ⑨一般株式等に係る譲渡所得等 →
      ⑩上場株式等に係る譲渡所得等）→ ⑫山林所得金額 → ⑬退職所得金額 の順で、ただし書で⑧〜⑩の間は納税者が異なる順序で控除して申告することを
      認める（docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md §3）。order が ORDER_TSUTATSU なら通達の順、ORDER_ALT なら
      譲渡所得等を先にする。stock_order_matters は2つの順で結果が違うか（違うときだけ式が選択の入力を引く）。
    - 第89条第2項の「残額」：0未満にしない。各課税標準は国税通則法第118条第1項で千円未満を切り捨てる。
    - 負の金額（損失）は控除の基礎にしない（0として扱う。総所得金額などは損益通算の後で負にならない）。
    """
    for name, v in (("総所得金額", 総所得), ("配当所得等", 配当), ("譲渡所得等", 譲渡), ("退職所得金額", 退職), ("所得控除の合計", 控除)):
        if type(v) is not int:
            raise TypeError(f"{name}は整数の円が必要")
    if 控除 < 0:
        raise ValueError("所得控除の合計が負")
    rest = 控除
    base_total = max(総所得, 0)
    d_total = min(base_total, rest)
    rest -= d_total
    d, g = max(配当, 0), max(譲渡, 0)
    # 順序A：配当所得等 → 譲渡所得等、順序B：譲渡所得等 → 配当所得等
    da = min(d, rest)
    ga = min(g, rest - da)
    gb = min(g, rest)
    db = min(d, rest - gb)
    rest -= da + ga  # どちらの順でも2つから控除する合計は同じ
    base_retire = max(退職, 0)
    d_retire = min(base_retire, rest)
    floor = lambda x: floor_to_unit(x, unit)  # noqa: E731
    a = (floor(d - da), floor(g - ga))
    b = (floor(d - db), floor(g - gb))
    if order not in ORDERS:
        raise ValueError(f"所得控除の順序が分からない: {order!r}")
    chosen = a if order == ORDER_TSUTATSU else b
    return Allocation(
        総所得=floor(base_total - d_total),
        配当=chosen[0],
        譲渡=chosen[1],
        退職=floor(base_retire - d_retire),
        stock_order_matters=a != b,
    )


# ---------------------------------------------------------------------------
# 税率（所得税法第89条第1項）
# ---------------------------------------------------------------------------

P_RATE = "所得税.税率"
#: 段の数（第7段は上端がない）。
N_BRACKETS = 7


@dataclass(frozen=True)
class Bracket:
    """第89条第1項の表の1段：up_to 以下（None なら上限なし）の部分に rate を乗じる。"""

    number: int
    up_to: int | None
    rate: Fraction

    def parameter_names(self) -> tuple[str, ...]:
        base = f"{P_RATE}.第{self.number}段"
        names = (f"{base}.率.分子", f"{base}.率.分母")
        return ((f"{base}.以下",) if self.up_to is not None else ()) + names


def brackets_from_parameters(p: Any) -> tuple[Bracket, ...]:
    """parameters(期間).所得税.税率 から段の列を作る（上端が増える順であることを確かめる）。"""
    out: list[Bracket] = []
    for n in range(1, N_BRACKETS + 1):
        node = getattr(p, f"第{n}段")
        up_to = _int(node.以下, f"{P_RATE}.第{n}段.以下") if n < N_BRACKETS else None
        out.append(Bracket(n, up_to, rate_of(node.率, f"{P_RATE}.第{n}段.率")))
    tops = [b.up_to for b in out[:-1]]
    if any(x is None for x in tops) or tops != sorted(set(tops)):  # type: ignore[type-var]
        raise ValueError("所得税法第89条第1項の段の上端が増える順でない")
    return tuple(out)


def progressive_tax(base: int, brackets: Sequence[Bracket]) -> tuple[int, tuple[Bracket, ...]]:
    """課税標準 base に超過累進税率を当てた税額と、使った段（base が0なら空）。

    課税標準は千円単位、率は百分率なので税額は整数になる。整数にならなければ（パラメータの誤り）止める。
    """
    if type(base) is not int or base < 0:
        raise ValueError("課税標準は0以上の整数の円")
    tax = Fraction(0)
    lower = 0
    used: list[Bracket] = []
    for b in brackets:
        if base <= lower:
            break
        top = base if b.up_to is None else min(base, b.up_to)
        tax += (top - lower) * b.rate
        used.append(b)
        if b.up_to is None or base <= b.up_to:
            break
        lower = b.up_to
    if tax.denominator != 1:
        raise ValueError(f"税額が整数にならない（課税標準 {base}）：課税標準の千円未満の切捨てか率を確かめる")
    return int(tax), tuple(used)


# ---------------------------------------------------------------------------
# 税額控除の差引（第一表 ㊷ 差引所得税額）
# ---------------------------------------------------------------------------

#: 第一表 ㊷ の差し引く順（令和7年分 確定申告の手引き 3-4_36：㉜ から ㉝・㉞・㉟・㊱〜㊳・㊴〜㊶ を差し引き、赤字は0）。
CREDIT_ORDER: tuple[str, ...] = (
    "配当控除",
    "事業所得等の特例に係る税額控除",
    "住宅借入金等特別控除",
    "政党等寄附金等特別控除",
    "住宅耐震改修特別控除等",
)


@dataclass(frozen=True)
class CreditDeduction:
    差引所得税額: int
    #: 控除ごとに実際に差し引いた額（CREDIT_ORDER と同じ順。前の控除の後に残った税額を限度にした額）
    差し引いた額: tuple[int, ...]


def deduct_credits(tax: int, credits: Sequence[int]) -> CreditDeduction:
    """算出税額（㉜）から税額控除の額（外部で計算した額などを CREDIT_ORDER の順に並べたもの）を順に差し引く（手引き 3-4_36。赤字は0）。

    各控除はその前の控除の後に残った税額を限度にする（控除しきれない額は差し引かない）。災害減免額（㊸）は後の段（D21 R3）。
    """
    _nonneg("算出税額", tax)
    rest = tax
    used: list[int] = []
    for c in credits:
        _nonneg("税額控除の額", c)
        d = min(rest, c)
        used.append(d)
        rest -= d
    return CreditDeduction(rest, tuple(used))


#: 区分の値で「書かない」（result.Category は空の文字列を受け付けない：forms/README §5-6）。
NO_CATEGORY = "なし"


def business_credit_category(amount: int) -> str:
    """第一表 ㉞ の区分（手引き 3-4_29）：事業所得等の特例に係る税額控除があれば「1」（左側の空欄に「投資税額等」）、なければ「なし」。"""
    _nonneg("税額控除の額", amount)
    return "1" if amount > 0 else NO_CATEGORY


def housing_credit_category(seismic: int, renovation: int, new_build: int) -> str:
    """第一表 ㊴〜㊶ の区分（手引き 3-4_32）：住宅耐震改修特別控除 1・住宅特定改修特別税額控除 2・認定住宅等新築等特別税額控除 3、
    複数の控除がある場合は 4（額は合計額）。どれもなければ「なし」。"""
    amounts = (seismic, renovation, new_build)
    for a in amounts:
        _nonneg("税額控除の額", a)
    present = [i for i, a in enumerate(amounts) if a > 0]
    if not present:
        return NO_CATEGORY
    if len(present) > 1:
        return "4"
    return str(present[0] + 1)


# ---------------------------------------------------------------------------
# 復興特別所得税
# ---------------------------------------------------------------------------


def fukko_tax(base_tax: int, rate: Fraction, round_fn: Any) -> int:
    """基準所得税額 × 税率 を round_fn（1円未満の端数処理）で丸める（復興財源確保法第13条）。基準所得税額は整数（第24条第1項）。"""
    if type(base_tax) is not int or base_tax < 0:
        raise ValueError("基準所得税額は0以上の整数の円")
    return int(round_fn(base_tax * rate))


# ---------------------------------------------------------------------------
# 精算（申告納税額・第3期分の税額・還付される税額）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settlement:
    申告納税額: int
    第3期分: int
    還付: int


def _nonneg(name: str, v: int) -> None:
    if type(v) is not int or v < 0:
        raise ValueError(f"{name}は0以上の整数の円")


def shinkoku_nozei(total_tax: int, withholding: int, unit: int) -> int:
    """手引き ㊿ 申告納税額：所得税及び復興特別所得税の額 − 源泉徴収税額。黒字は百円未満切捨て（通則法第119条第1項・
    復興法第24条第2項）、赤字は0（控除しきれない源泉徴収税額は refund の側）。"""
    _nonneg("所得税及び復興特別所得税の額", total_tax)
    _nonneg("源泉徴収税額", withholding)
    a = total_tax - withholding
    return floor_to_unit(a, unit) if a > 0 else 0


def shinkoku_nozei_field(total_tax: int, withholding: int, unit: int) -> int:
    """申告書 第一表 ㊿ の欄に書く額（2026-11-13）：所得税及び復興特別所得税の額 − 源泉徴収税額。黒字は百円未満切捨て、
    赤字はそのままの金額（手引き 53 の「申告納税額は、黒字なら百円未満切捨て後、赤字ならそのままの金額」と同じ読み。refund_amount の a）。
    申告納税額（shinkoku_nozei）は赤字を0にするが、欄には赤字を書く（作成コーナーとの照合 A01・C01：還付の申告で ㊿ に -61231・-7760）。"""
    _nonneg("所得税及び復興特別所得税の額", total_tax)
    _nonneg("源泉徴収税額", withholding)
    a = total_tax - withholding
    return floor_to_unit(a, unit) if a >= 0 else a


def third_installment(shinkoku: int, prepaid: int, unit: int) -> int:
    """手引き 52：第3期分の税額＝申告納税額 − 予定納税額。黒字は百円未満切捨て、赤字は0（還付の側）。"""
    _nonneg("申告納税額", shinkoku)
    _nonneg("予定納税額", prepaid)
    x = shinkoku - prepaid
    return floor_to_unit(x, unit) if x > 0 else 0


def refund_amount(total_tax: int, withholding: int, prepaid: int, unit: int) -> int:
    """手引き 53：還付される税金＝（申告納税額 − 予定納税額）の赤字。申告納税額は、黒字なら百円未満切捨て後、赤字ならそのままの金額。
    控除しきれない源泉徴収税額（所得税法第122条第1項第2号）と予納税額（第3号）の合計。還付金の1円未満は切捨て（通則法第120条第1項。
    金額は整数なので切り捨てる端数はない）。"""
    _nonneg("所得税及び復興特別所得税の額", total_tax)
    _nonneg("源泉徴収税額", withholding)
    _nonneg("予定納税額", prepaid)
    a = total_tax - withholding
    second = (floor_to_unit(a, unit) if a >= 0 else a) - prepaid
    return -second if second < 0 else 0


def settle(total_tax: int, withholding: int, prepaid: int, unit: int) -> Settlement:
    """手引きの順（zeigaku §3.3）の精算をまとめて返す（テストと根拠の確かめ用。式は3つの関数を別々に使う）。"""
    s = shinkoku_nozei(total_tax, withholding, unit)
    return Settlement(申告納税額=s, 第3期分=third_installment(s, prepaid, unit), 還付=refund_amount(total_tax, withholding, prepaid, unit))


# ---------------------------------------------------------------------------
# 配当控除（所得税法第92条）
# ---------------------------------------------------------------------------

#: 配当控除の額の1円未満の端数を切り捨てる（所法92 に定めがなく、国税通則法基本通達第119条関係6 の一般の定めに従う読み）。
HAITO_FLOOR = RoundingRule(
    name="floor_yen_haito_kojo_tsutatsu",
    title="配当控除の額（率を乗じた金額）の1円未満の端数を切り捨てる",
    function="floor",
    source_kind=SourceKind.CIRCULAR,
    law=(
        "所得税法第92条に端数の定めはない。国税通則法基本通達（徴収部関係）第119条関係6（「国税の確定金額を算出する過程におけるその算出額に、"
        "1円未満の端数があるときは、その端数金額を切り捨てるものとする」）の一般の定めに従う。配当控除の額に当てるのは法令の読み（作成コーナーとの照合が要る）"
    ),
    references=(
        "docs/public-sources/20261111_impl-research_hasu-tebiki-and-nta.md#5",
        "docs/public-sources/20261111_impl-research_haito-laws-and-nta.md#5",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
)


@dataclass(frozen=True)
class DividendCreditRules:
    """配当控除の式（所法92①、措法9④ の読替え）。"""

    threshold: int  # 課税総所得金額等の基準（千万円）
    a_rate: Fraction  # 剰余金の配当等の高い率（百分の十）
    a_low_rate: Fraction  # 同じく低い率（百分の五）
    b_rate: Fraction  # 証券投資信託の収益の分配の高い率（百分の五）
    b_low_rate: Fraction  # 同じく低い率（百分の二・五）
    c_rate: Fraction  # 一般外貨建等証券投資信託の収益の分配の高い率（百分の二・五：措法9④）
    c_low_rate: Fraction  # 同じく低い率（百分の一・二五：措法9④）


def dividend_credit_rules_from_parameters(p: Any) -> DividendCreditRules:
    return DividendCreditRules(
        threshold=_int(p.課税総所得金額等の基準, "所得税.配当控除.課税総所得金額等の基準"),
        a_rate=rate_of(p.剰余金の配当等の率, "剰余金の配当等の率"),
        a_low_rate=rate_of(p.剰余金の配当等の低い率, "剰余金の配当等の低い率"),
        b_rate=rate_of(p.証券投資信託の率, "証券投資信託の率"),
        b_low_rate=rate_of(p.証券投資信託の低い率, "証券投資信託の低い率"),
        c_rate=rate_of(p.一般外貨建等証券投資信託の率, "一般外貨建等証券投資信託の率"),
        c_low_rate=rate_of(p.一般外貨建等証券投資信託の低い率, "一般外貨建等証券投資信託の低い率"),
    )


def dividend_credit(taxable: int, a: int, b: int, tax: int, rules: DividendCreditRules, c: int = 0) -> int:
    """配当控除の額：計算した額（dividend_credit_computed）と所得税額の小さいほう（限度は所得税額：第92条第2項）。"""
    if tax < 0:
        raise ValueError("配当控除の基礎は0以上の整数の円")
    return min(dividend_credit_computed(taxable, a, b, rules, c), tax)


def dividend_credit_computed(taxable: int, a: int, b: int, rules: DividendCreditRules, c: int = 0) -> int:
    """配当控除の計算した額（所法92①の第1号〜第3号と措法9④ の読替え。1円未満は切捨て。所得税額の限度の前。
    2026-11-13 に dividend_credit から分けた：申告書 第一表 ㉝ には手引きの計算欄G（E＋F）の額を書き、限度は ㊷ の側で効く
    〔手引き 3-4_28「〔33〕欄 … 計算欄Gの金額を転記します」。作成コーナーとの照合 B01 で ㉝ 20,000・税額 10,050 を観測〕）。

    taxable は課税総所得金額等（課税総所得金額に上場株式等の課税配当所得等・課税譲渡所得等を足した額：措法8の4③四・37の10⑥六の読替え）。
    a は剰余金の配当等（特定株式投資信託の収益の分配を含む：措法9③）に係る配当所得の金額、b は証券投資信託（特定株式投資信託・
    一般外貨建等証券投資信託を除く）の収益の分配に係る配当所得の金額、c は一般外貨建等証券投資信託の収益の分配に係る配当所得の金額
    （措法9④。所法92 の「証券投資信託の収益の分配に係る配当所得」は b＋c）。
    """
    if min(taxable, a, b, c) < 0:
        raise ValueError("配当控除の基礎は0以上の整数の円")
    t, th = taxable, rules.threshold
    trust = b + c  # 所法92① ロの「証券投資信託の収益の分配に係る配当所得の金額」
    if t <= th:  # 第1号（措法9④ の第1号ロの読替え）
        credit = a * rules.a_rate + b * rules.b_rate + c * rules.c_rate
    elif t - trust <= th:  # 第2号（措法9④ の第2号ロの読替え）
        if t - c <= th:
            part_c = min(t - th, c)
            credit = a * rules.a_rate + part_c * rules.c_low_rate + (c - part_c) * rules.c_rate + b * rules.b_rate
        else:
            part_b = min(t - th - c, b)
            credit = a * rules.a_rate + c * rules.c_low_rate + part_b * rules.b_low_rate + (b - part_b) * rules.b_rate
    else:  # 第3号（措法9④ の第3号ロの読替え）
        part = min(t - th - trust, a)
        credit = part * rules.a_low_rate + (a - part) * rules.a_rate + b * rules.b_low_rate + c * rules.c_low_rate
    return HAITO_FLOOR.apply(credit)


# ---------------------------------------------------------------------------
# 申告の要否（所得税法第120条第1項・第121条。措令4の2⑧・25の8⑮・25の9⑬ の読替え）
# ---------------------------------------------------------------------------

#: 判定できない理由（checks.py が対象外の理由に使う。どれも入力の不足：c-入力）。
REASON_121_SALARY = (
    "所得税法第121条第1項（給与所得者の確定申告を要しない場合）が当たりうる（給与等の金額が2,000万円以下）が、判定の事実が足りない"
    "（docs/public-sources/20261111_impl-research_121-laws-and-nta.md §1）"
)
REASON_121_SECONDARY = (
    "二以上の支払者から給与等を受けている（所得税法第121条第1項第2号）。従たる給与等の金額が源泉徴収票の記載から分からず（secondary_column）、"
    "第2号イの判定ができない（docs/public-sources/20261111_impl-research_121-laws-and-nta.md §1）"
)
REASON_121_RETIREMENT = (
    "所得税法第121条第2項（退職所得の確定申告を要しない場合）が当たりうる（課税退職所得金額に対する税額がある）が、判定の事実が足りない"
    "（docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md §4.1）"
)
REASON_121_PENSION = (
    "所得税法第121条第3項（公的年金等の確定申告を要しない場合）が当たりうる（公的年金等の収入金額が400万円以下）が、判定の事実が足りない"
    "（docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md §6）"
)


@dataclass(frozen=True)
class Obligation:
    value: bool
    unresolved: tuple[str, ...]  # 空でなければ判定できない（呼ぶ側が対象外にする）


@dataclass(frozen=True)
class SalaryFacts:
    """第121条第1項の判定の事実。other_income は給与所得及び退職所得以外の所得金額（基通121−6）。"""

    payers: int
    all_withheld: bool  # 全部について第183条・第190条の規定による徴収をされた又はされるべき（第184条の家事使用人等は記録にない）
    all_year_end_adjusted: bool  # 全部について第190条の適用がある（基通121−4 で第1号に当たる）
    secondary_salary: int  # 従たる給与等の金額
    secondary_known: bool  # 従たる給与等の金額が分かるか
    other_income: int
    deductions: int  # 第2号ロの控除の額の合計
    other_limit: int  # 二十万円
    small_salary_limit: int  # 第2号ロの百五十万円
    excluded: bool = False  # 基通121−5(1)(3)・所令262の2（第1項ただし書）に当たる支払を受けた


@dataclass(frozen=True)
class PensionFacts:
    """第121条第3項の判定の事実。other_income は公的年金等に係る雑所得以外の所得金額（基通121−6）。"""

    all_withheld: bool
    other_income: int
    other_limit: int


@dataclass(frozen=True)
class RetirementFacts:
    """第121条第2項の判定の事実。all_withheld は第1号（第199条・第201条第1項の徴収）に当たるか、withheld は源泉徴収税額（第2号）。"""

    all_withheld: bool
    withheld: int


def salary_return_not_required(salary: int, salary_limit: int, f: SalaryFacts) -> bool | None:
    """第121条第1項に当たれば True、当たらなければ False、決められなければ None。"""
    if salary == 0 or salary > salary_limit or not f.all_withheld or f.excluded:
        return False
    if f.payers <= 1 or f.all_year_end_adjusted:  # 第1号（基通121−4）
        return f.other_income <= f.other_limit
    # 第2号
    ro = salary <= f.small_salary_limit + f.deductions and f.other_income <= f.other_limit
    if not f.secondary_known:
        return True if ro else None
    return ro or f.secondary_salary + f.other_income <= f.other_limit


def filing_obligation(
    *,
    tax_total_income: int,
    tax_retirement: int,
    tax_separate_dividend: int,
    tax_separate_gain: int,
    dividend_credit: int,
    year_end_housing_credit: int,
    refund: int,
    salary: int,
    pension: int,
    salary_limit: int,
    pension_limit: int,
    salary_facts: SalaryFacts | None = None,
    pension_facts: PensionFacts | None = None,
    retirement_facts: RetirementFacts | None = None,
) -> Obligation:
    """確定申告書を提出しなければならないか（所得税法第120条第1項・第121条）。

    - A（第120条第1項本文）：総所得金額・上場株式等の所得・退職所得金額から所得控除を第87条第2項に準じて控除した額に第89条等を当てた税額の合計
      （課税総所得金額・課税退職所得金額・上場株式等の課税所得に対する税額の合計。措令4の2⑧・25の8⑮の読替え）が配当控除の額を超える。
      「配当控除の額」は措法41の2の2⑥二で「配当控除の額と…第四十一条の二の二第一項…の規定により控除される金額との合計額」と読み替える
      （year_end_housing_credit：年末調整で控除された住宅借入金等特別控除の額。確定申告で初めて受ける額は加えない：
      docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md §4）。
    - B（同かっこ書き）：控除しきれない源泉徴収税額・予納税額がある（＝還付される税額が0超。所得税と復興特別所得税の合計で比べる：仮説 H7、法令の読み）。
    - A が偽、又は B が真なら義務はない（偽）。それ以外は、第1項・第3項が総合課税と上場株式等の所得の税額を、第2項が退職所得の税額をそれぞれ
      申告不要にする（第121条。税額があってどちらかが当たらなければ義務がある）。決められない事実は unresolved に入れる。
    """
    unresolved: list[str] = []
    tax_general = tax_total_income + tax_separate_dividend + tax_separate_gain
    tax = tax_general + tax_retirement
    if year_end_housing_credit < 0:
        raise ValueError("年末調整で控除された住宅借入金等特別控除の額が負")
    if not tax > dividend_credit + year_end_housing_credit or refund > 0:
        return Obligation(False, tuple(unresolved))
    # 第1項（給与）
    if salary_facts is not None:
        salary_nr = salary_return_not_required(salary, salary_limit, salary_facts)
        if salary_nr is None:
            unresolved.append(REASON_121_SECONDARY)
    elif 0 < salary <= salary_limit:
        salary_nr = None
        unresolved.append(REASON_121_SALARY)
    else:
        salary_nr = False
    # 第3項（公的年金等）
    pension_nr: bool | None
    if pension_facts is not None:
        pension_nr = 0 < pension <= pension_limit and pension_facts.all_withheld and pension_facts.other_income <= pension_facts.other_limit
    elif 0 < pension <= pension_limit:
        pension_nr = None
        unresolved.append(REASON_121_PENSION)
    else:
        pension_nr = False
    general_nr: bool | None
    if salary_nr is True or pension_nr is True:
        general_nr = True
    elif salary_nr is None or pension_nr is None:
        general_nr = None
    else:
        general_nr = False
    # 第2項（退職）
    retire_nr: bool | None
    if tax_retirement == 0:
        retire_nr = True
    elif retirement_facts is not None:
        retire_nr = retirement_facts.all_withheld or tax_retirement <= retirement_facts.withheld
    else:
        retire_nr = None
        unresolved.append(REASON_121_RETIREMENT)
    obliged = (tax_general > 0 and general_nr is not True) or (tax_retirement > 0 and retire_nr is not True)
    return Obligation(obliged, tuple(unresolved))


# ---------------------------------------------------------------------------
# 休日と期限（国税通則法第10条、祝日法第2条・第3条、通則令第2条第2項、通達、暦要項）
# ---------------------------------------------------------------------------

_MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")
_NTH_MONDAY = re.compile(r"^(\d{2})-第([1-5])月曜日$")
UNPUBLISHED = "未発表"
P_HOLIDAY = "所得税.休日"
#: 暦要項が未発表の年に休日が決まらない月（春分日・秋分日と、それに続く振替休日・国民の休日はその月の中）。
_EQUINOX_MONTH: Mapping[str, int] = {"春分の日": 3, "秋分の日": 9}


class CalendarUnknown(ValueError):
    """その暦年の休日が一次情報で決まらない（暦要項が未発表など）。"""


@dataclass(frozen=True)
class Calendar:
    """1つの暦年の、期限が繰り下がる日（日曜日を除く。日曜日は is_closed が見る）。"""

    year: int
    national: frozenset[_dt.date]  # 国民の祝日（祝日法第2条）
    substitute: frozenset[_dt.date]  # 振替休日（第3条第2項）・国民の休日（第3条第3項）
    general: frozenset[_dt.date]  # その他一般の休日（通達：1月2日・3日）
    ordinance: frozenset[_dt.date]  # 政令で定める日（12月29日〜31日）
    saturday: bool  # 政令で定める日に土曜日を含むか
    unknown_months: frozenset[int] = frozenset()  # 暦要項が未発表で休日が決まらない月（春分日の3月・秋分日の9月）

    def is_closed(self, d: _dt.date) -> bool:
        if d.year != self.year:
            raise ValueError("別の暦年の日")
        if d.weekday() == 6:  # 日曜日（通則法第10条第2項）
            return True
        if self.saturday and d.weekday() == 5:
            return True
        return d in self.national or d in self.substitute or d in self.general or d in self.ordinance


def _parse_day(year: int, text: str, where: str) -> _dt.date:
    if not isinstance(text, str):
        raise TypeError(f"{where} は文字列が必要")
    if text == UNPUBLISHED:
        raise CalendarUnknown(f"{year}年の {where} が未発表（暦要項）")
    m = _MONTH_DAY.match(text)
    if m:
        return _dt.date(year, int(m.group(1)), int(m.group(2)))
    m = _NTH_MONDAY.match(text)
    if m:
        month, nth = int(m.group(1)), int(m.group(2))
        first = _dt.date(year, month, 1)
        offset = (0 - first.weekday()) % 7  # 最初の月曜日まで
        d = first + _dt.timedelta(days=offset + 7 * (nth - 1))
        if d.month != month:
            raise ValueError(f"{where}：{year}年{month}月に第{nth}月曜日がない")
        return d
    raise ValueError(f"{where} の書き方が分からない: {text!r}")


def _children(node: Any) -> Iterable[tuple[str, Any]]:
    """ParameterNodeAtInstant（追跡つきでもよい）の子（名前の順。決定的にする）。添字で引くので追跡に残る。"""
    for n in sorted(node):
        yield n, node[n]


def calendar_from_parameters(year: int, h: Any) -> Calendar:
    """parameters(その暦年の1月1日).所得税.休日 から、その暦年の休日を作る。暦要項が未発表の月は unknown_months に入れる。"""
    national: set[_dt.date] = set()
    unknown: set[int] = set()
    for k, v in _children(h.国民の祝日):
        if v == UNPUBLISHED:
            if k not in _EQUINOX_MONTH:
                raise ValueError(f"{P_HOLIDAY}.国民の祝日.{k} は未発表にできない")
            unknown.add(_EQUINOX_MONTH[k])
            continue
        national.add(_parse_day(year, v, f"{P_HOLIDAY}.国民の祝日.{k}"))
    general = {_parse_day(year, v, f"{P_HOLIDAY}.一般の休日.{k}") for k, v in _children(h.一般の休日)}
    rei = h.政令で定める日
    saturday = rei.土曜日
    if type(saturday) is not bool:
        raise TypeError("所得税.休日.政令で定める日.土曜日 は真偽が必要")
    ordinance = {
        _parse_day(year, v, f"{P_HOLIDAY}.政令で定める日.{k}") for k, v in _children(rei) if k != "土曜日"
    }
    return Calendar(
        year, frozenset(national), frozenset(substitute_holidays(national)), frozenset(general), frozenset(ordinance), saturday, frozenset(unknown)
    )


def substitute_holidays(national: Iterable[_dt.date]) -> set[_dt.date]:
    """祝日法第3条第2項（「国民の祝日」が日曜日に当たるときは、その日後においてその日に最も近い「国民の祝日」でない日）と
    第3項（その前日及び翌日が「国民の祝日」である日〔「国民の祝日」でない日に限る〕）の休日。"""
    nat = set(national)
    out: set[_dt.date] = set()
    for d in sorted(nat):
        if d.weekday() == 6:
            x = d + _dt.timedelta(days=1)
            while x in nat:
                x += _dt.timedelta(days=1)
            out.add(x)
    for d in sorted(nat):
        x = d + _dt.timedelta(days=1)
        if x not in nat and x + _dt.timedelta(days=1) in nat:
            out.add(x)
    return out


def next_open_day(d: _dt.date, calendars: Mapping[int, Calendar]) -> _dt.date:
    """d が休日なら、休日でない最初の日（国税通則法第10条第2項：休日の翌日を期限とみなす）。暦年の休日がなければ CalendarUnknown。"""
    x = d
    for _ in range(31):
        cal = calendars.get(x.year)
        if cal is None:
            raise CalendarUnknown(f"{x.year}年の休日のパラメータがない")
        if x.month in cal.unknown_months:
            raise CalendarUnknown(f"{x.year}年{x.month}月の休日が決まらない（暦要項が未発表）")
        if not cal.is_closed(x):
            return x
        x += _dt.timedelta(days=1)
    raise ValueError("休日が続きすぎる（パラメータの誤り）")


def third_period_end(tax_year: int, month_day: str) -> _dt.date:
    """第三期の末日（その年の翌年の3月15日。所得税法第120条第1項）。"""
    m = _MONTH_DAY.match(month_day) if isinstance(month_day, str) else None
    if m is None:
        raise ValueError(f"所得税.申告期限.第三期の末日 の書き方が分からない: {month_day!r}")
    return _dt.date(tax_year + 1, int(m.group(1)), int(m.group(2)))


def normal_deadline(tax_year: int, month_day: str, calendars: Mapping[int, Calendar]) -> _dt.date:
    """第120条第1項の確定申告書の提出期限：第三期の末日。休日なら繰り下げる（国税通則法第10条第2項）。"""
    return next_open_day(third_period_end(tax_year, month_day), calendars)


def months_later_expiry(start_next_day: _dt.date, months: int) -> _dt.date:
    """国税通則法第10条第1項第2号・第3号：起算日 start_next_day から months 月の期間の満了日
    （最後の月の起算日に応当する日の前日。応当する日がなければその月の末日）。"""
    if type(months) is not int or months <= 0:
        raise ValueError("月数は1以上の整数")
    y, m = divmod(start_next_day.month - 1 + months, 12)
    year, month = start_next_day.year + y, m + 1
    last = calendar.monthrange(year, month)[1]
    if start_next_day.day > last:
        return _dt.date(year, month, last)
    return _dt.date(year, month, start_next_day.day) - _dt.timedelta(days=1)


def death_deadline(
    known_on: _dt.date, months: int, calendars: Mapping[int, Calendar], heir_departure_on: _dt.date | None = None
) -> _dt.date:
    """所得税法第125条第1項（第124条第1項も同じ形）：相続の開始があったことを知った日の翌日から months 月を経過した日の前日
    （読みA：翌日を起算日とする期間の満了日。実測 §4 [2] で付表の書き方の例と一致）。休日なら繰り下げる（通則法第10条第2項）。
    その前に相続人が出国をするなら出国の時（時をもって定める期限は繰り下げない：通則令第2条第1項第1号）。
    """
    expiry = next_open_day(months_later_expiry(known_on + _dt.timedelta(days=1), months), calendars)
    if heir_departure_on is not None and heir_departure_on < expiry:
        return heir_departure_on
    return expiry


__all__ = [
    "ORDERS",
    "ORDER_ALT",
    "ORDER_TSUTATSU",
    "Allocation",
    "Bracket",
    "DividendCreditRules",
    "HAITO_FLOOR",
    "PensionFacts",
    "RetirementFacts",
    "SalaryFacts",
    "Calendar",
    "CalendarUnknown",
    "FUKKO_ROUNDING_YEARS",
    "FUKKO_TEBIKI_FLOOR_R7",
    "FUKKO_TSUTATSU_FLOOR_R8",
    "KAKUTEI_KINGAKU_FLOOR",
    "KAZEI_HYOJUN_FLOOR",
    "Obligation",
    "Settlement",
    "UnitFloor",
    "allocate_deductions",
    "brackets_from_parameters",
    "calendar_from_parameters",
    "death_deadline",
    "dividend_credit",
    "dividend_credit_computed",
    "dividend_credit_rules_from_parameters",
    "filing_obligation",
    "fukko_tax",
    "months_later_expiry",
    "next_open_day",
    "normal_deadline",
    "progressive_tax",
    "rate_of",
    "refund_amount",
    "salary_return_not_required",
    "settle",
    "shinkoku_nozei",
    "shinkoku_nozei_field",
    "substitute_holidays",
    "third_installment",
    "third_period_end",
]

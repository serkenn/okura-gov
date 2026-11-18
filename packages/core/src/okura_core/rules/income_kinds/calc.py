"""規則モジュール income_kinds の純粋関数（OpenFisca の式とテストの両方が使う。規則の置き場所は1か所）。

金額は整数の円、途中の値は Fraction（float を使わない。D21 R5）。円未満の端数の定めがない値（公的年金等控除額・退職所得の金額の
2分の1）は、呼び出し側が渡す丸めの関数 `round_income`（根拠のない端数の候補：切捨て・切上げ・四捨五入。D22 S3）で
**所得の金額の側** を丸める。公的年金等控除額は「収入金額 − 丸めた所得の金額」で整数にする（候補の向きを所得の金額でそろえ、
合計所得金額などの和の幅の端〔全部切捨て・全部切上げ〕が候補に入るようにするため。README §4）。

パラメータは parameters(期間)（OpenFisca の ParameterNodeAtInstant。追跡つきでもよい）から読む。名前は parameters/所得税/*.yaml。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...basis import ReadingFlag, SourceKind
from ...rounding import RoundingRule

RoundFn = Callable[[Fraction], int]

P_PENSION = "所得税.公的年金等控除額"
P_WINDFALL = "所得税.一時所得.特別控除額"
P_RETIRE = "所得税.退職所得"
P_HOME_WORKER = "所得税.家内労働者等の必要経費の特例.額"
P_BLUE = "所得税.青色申告特別控除"

#: 退職手当等の区分（入力 所得税_退職手当等の区分 の値）。
RETIRE_GENERAL = "一般"
RETIRE_SHORT = "短期"
RETIRE_OFFICER = "特定役員"
RETIRE_KINDS = (RETIRE_GENERAL, RETIRE_SHORT, RETIRE_OFFICER)

#: 根拠のある端数処理（D21 R5：法令＞通達＞手引き＞国税庁の説明。法令以外は根拠の種類で分かる）。
PENSION_FLOOR = RoundingRule(
    name="floor_yen_koteki_nenkin_zatsu",
    title="公的年金等に係る雑所得の金額の1円未満の端数を切り捨てる",
    function="floor",
    source_kind=SourceKind.GUIDE_OR_FORM_NOTE,
    law="確定申告の手引き（令和7年分）3-2_07 の計算表の注「1円未満の端数があるときは、その端数を切り捨てます」（令和8年分の手引きは未公表で、令和7年分を使う）",
    references=(
        "docs/public-sources/20261111_impl-research_hasu-tebiki-and-nta.md#3",
        "docs/hypotheses/20261111_impl-research_hasu-model.md#H2",
    ),
)

DEPRECIATION_CEIL = RoundingRule(
    name="ceil_yen_genka_shokyakuhi",
    title="減価償却費（取得価額×償却率×月数／12）の1円未満の端数を切り上げる",
    function="ceil",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="確定申告書等作成コーナー よくある質問「減価償却費の端数処理」（令和5〜7年分。「切上げ処理を行っています」。法令・通達には定めがない）",
    references=(
        "docs/public-sources/20261111_impl-research_genka-hasu-nta.md#2",
        "docs/hypotheses/20261111_impl-research_genka-hasu-model.md#H1",
    ),
    flags=(ReadingFlag.LEGAL_READING,),
)

#: 青色申告の承認の状態（入力 所得税_青色申告の承認の状態 の値）。
BLUE_APPROVED = "承認"
BLUE_NOT_APPROVED = "承認なし"

#: 青色申告特別控除の申告の要件（入力 所得税_青色申告特別控除の申告の要件 の値。措法25の2③・④・⑥）。
FILING_ETAX = "期限内の電子申告"
FILING_PAPER = "期限内の書面の申告"
FILING_OTHER = "期限内の申告でない"
#: 書面の申告で、仕訳帳・総勘定元帳を優良な電子帳簿で備え付け・保存し届出をしている（措法25の2④一。2026-11-12）
FILING_EBOOKS = "期限内の書面の申告（優良な電子帳簿）"
FILING_KINDS = (FILING_ETAX, FILING_PAPER, FILING_OTHER, FILING_EBOOKS)


def _int(v: Any, name: str) -> int:
    if type(v) is not int:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise TypeError(f"パラメータ {name} は整数が必要（{type(v).__name__}）") from None
        if iv != v or isinstance(v, (bool, float)):
            raise TypeError(f"パラメータ {name} は整数が必要（{v!r}）")
        return iv
    return v


def _rate(node: Any, name: str) -> Fraction:
    return Fraction(_int(node.分子, f"{name}.分子"), _int(node.分母, f"{name}.分母"))


# ---------------------------------------------------------------------------
# 公的年金等控除額（所得税法第35条第4項、租税特別措置法第41条の15の3）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PensionRules:
    upper_1: int
    upper_2: int
    base: tuple[int, int, int]
    minimum: tuple[int, int, int]
    minimum_65: tuple[int, int, int]
    age_65: int
    ro_offset: int
    ro_brackets: tuple[tuple[int, int, int, Fraction], ...]  # (上限, 基礎, 控除する額, 率)
    ro_top: int


def pension_rules(p: Any) -> PensionRules:
    n = p.所得税.公的年金等控除額
    ro = n.ロ
    b1 = (_int(ro.第1区分.上限, "ロ.第1区分.上限"), 0, 0, _rate(ro.第1区分.率, "ロ.第1区分.率"))
    b2 = (_int(ro.第2区分.上限, "ロ.第2区分.上限"), _int(ro.第2区分.基礎, "ロ.第2区分.基礎"), b1[0], _rate(ro.第2区分.率, "ロ.第2区分.率"))
    b3 = (_int(ro.第3区分.上限, "ロ.第3区分.上限"), _int(ro.第3区分.基礎, "ロ.第3区分.基礎"), b2[0], _rate(ro.第3区分.率, "ロ.第3区分.率"))
    s = n.六十五歳以上の特例
    return PensionRules(
        upper_1=_int(n.区分.第1号の上限, "区分.第1号の上限"),
        upper_2=_int(n.区分.第2号の上限, "区分.第2号の上限"),
        base=tuple(_int(getattr(n.イ, f"第{i}号"), f"イ.第{i}号") for i in (1, 2, 3)),  # type: ignore[arg-type]
        minimum=tuple(_int(getattr(n.最低額, f"第{i}号"), f"最低額.第{i}号") for i in (1, 2, 3)),  # type: ignore[arg-type]
        minimum_65=tuple(_int(getattr(s.最低額, f"第{i}号"), f"65歳.最低額.第{i}号") for i in (1, 2, 3)),  # type: ignore[arg-type]
        age_65=_int(s.年齢, "六十五歳以上の特例.年齢"),
        ro_offset=_int(ro.収入金額から控除する額, "ロ.収入金額から控除する額"),
        ro_brackets=(b1, b2, b3),
        ro_top=_int(ro.第4区分の額, "ロ.第4区分の額"),
    )


def pension_deduction(income: int, other_income: int, age: int, r: PensionRules) -> Fraction:
    """公的年金等控除額（有理数）。income は公的年金等の収入金額、other_income は公的年金等に係る雑所得以外の合計所得金額。

    第1号〜第3号の区分は other_income で決め、イ＋ロの合計額が最低額に満たなければ最低額（65歳以上は措法41の15の3①の読替え）。
    「収入金額から五十万円を控除した残額」は収入金額が五十万円に満たなければ0とする（最低額が上回るので結果に影響しない：
    docs/measurements/20261109_round2b_nenkin-fetch-and-checks.md の式 kojo_law と同じ扱い）。
    """
    if type(income) is not int or income < 0:
        raise ValueError("公的年金等の収入金額は0以上の整数の円")
    if income == 0:
        return Fraction(0)
    i = 0 if other_income <= r.upper_1 else 1 if other_income <= r.upper_2 else 2
    rest = max(0, income - r.ro_offset)
    ro: Fraction
    for upper, base, minus, rate in r.ro_brackets:
        if rest <= upper:
            ro = base + (rest - minus) * rate
            break
    else:
        ro = Fraction(r.ro_top)
    total = r.base[i] + ro
    minimum = r.minimum_65[i] if age >= r.age_65 else r.minimum[i]
    return max(Fraction(total), Fraction(minimum))


def pension_income(income: int, deduction: Fraction, round_income: RoundFn) -> int:
    """公的年金等に係る雑所得の金額（所法35②一「収入金額から公的年金等控除額を控除した残額」。控除額の方が大きければ0）。"""
    rest = income - deduction
    if rest <= 0:
        return 0
    return round_income(rest)


def pension_deduction_yen(income: int, deduction: Fraction, round_income: RoundFn) -> int:
    """結果に出す整数の公的年金等控除額：所得の金額が正なら「収入金額 − 丸めた所得の金額」、そうでなければ控除額そのもの。"""
    if income > deduction:
        return income - pension_income(income, deduction, round_income)
    if deduction.denominator != 1:  # 控除額 ≥ 収入金額のときは最低額（整数）になる（calc の docstring・テストで確かめる）
        raise ValueError(f"収入金額以上の公的年金等控除額が整数でない: {deduction}")
    return int(deduction)


# ---------------------------------------------------------------------------
# 一時所得（所得税法第34条）
# ---------------------------------------------------------------------------


def windfall_income(total: int, expenses: int, special: int) -> int:
    """一時所得の金額：総収入金額 − 支出した金額 − 特別控除額（五十万円。残額が五十万円に満たなければ当該残額）。

    残額が0以下なら特別控除額は当該残額で、一時所得の金額は0（第3項）。2分の1（所法22②二）は総所得金額を作る側（income_totals）。
    """
    rest = total - expenses
    if rest <= 0:
        return 0
    return rest - min(special, rest)


# ---------------------------------------------------------------------------
# 退職所得（所得税法第30条）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetirementRules:
    years_split: int
    per_year: int
    base_over: int
    per_year_over: int
    minimum: int
    disability_add: int
    half: Fraction
    short_split: int
    short_base: int


def retirement_rules(p: Any) -> RetirementRules:
    n = p.所得税.退職所得
    d = n.退職所得控除額
    return RetirementRules(
        years_split=_int(d.勤続年数の区分, "勤続年数の区分"),
        per_year=_int(d.一年当たりの額, "一年当たりの額"),
        base_over=_int(d.二十年を超える場合の基礎, "二十年を超える場合の基礎"),
        per_year_over=_int(d.二十年を超える一年当たりの額, "二十年を超える一年当たりの額"),
        minimum=_int(d.最低額, "最低額"),
        disability_add=_int(d.障害退職の加算額, "障害退職の加算額"),
        half=_rate(n.二分の一, "二分の一"),
        short_split=_int(n.短期退職手当等.残額の区分, "短期退職手当等.残額の区分"),
        short_base=_int(n.短期退職手当等.第2号の基礎, "短期退職手当等.第2号の基礎"),
    )


def deduction_by_years(years: int, r: RetirementRules) -> int:
    """所法30③の式（勤続年数 years に応じた額）。years が0なら0（所令70①二の重複期間が1年未満で切り捨てられた場合）。"""
    if type(years) is not int or years < 0:
        raise ValueError("年数は0以上の整数")
    if years <= r.years_split:
        return r.per_year * years
    return r.base_over + r.per_year_over * (years - r.years_split)


def retirement_deduction(years: int, disability: bool, r: RetirementRules, prior_years: int = 0) -> int:
    """退職所得控除額（所法30③・⑥）。prior_years は前の退職手当等との重複期間の年数（所令70①二・③：1年未満切捨て）で、
    その年数を勤続年数とみなして③で計算した額を控除する（⑥一）。⑥二の80万円の最低額は⑥一の後、⑥三の障害退職の加算はその後。"""
    if type(years) is not int or years < 1:
        raise ValueError("勤続年数は1以上の整数（所令69②：1年未満の端数は1年）")
    base = deduction_by_years(years, r) - deduction_by_years(prior_years, r)
    out = max(base, r.minimum)
    if disability:
        out += r.disability_add
    return out


def retirement_income(income: int, deduction: int, kind: str, r: RetirementRules, round_income: RoundFn) -> int:
    """退職所得の金額（所法30②）。kind は 一般・短期・特定役員。"""
    if kind not in RETIRE_KINDS:
        raise ValueError(f"退職手当等の区分が不明: {kind!r}")
    rest = income - deduction
    if rest <= 0:
        return 0
    if kind == RETIRE_OFFICER:
        return rest
    if kind == RETIRE_SHORT and rest > r.short_split:
        return r.short_base + (income - (r.short_split + deduction))
    return round_income(rest * r.half)


def retirement_has_fraction(income: int, deduction: int, kind: str, r: RetirementRules) -> bool:
    """退職所得の金額に1円未満の端数が出るか（出ないなら根拠のない端数の候補に依存しない）。"""
    rest = income - deduction
    if rest <= 0 or kind == RETIRE_OFFICER or (kind == RETIRE_SHORT and rest > r.short_split):
        return False
    return (rest * r.half).denominator != 1


def _half_part(rest: Fraction, r: RetirementRules) -> Fraction:
    return max(Fraction(0), rest) * r.half


def _short_part(rest: Fraction, r: RetirementRules) -> Fraction:
    """短期退職手当等の部分：残額 rest が300万円以下なら2分の1、超えるなら150万円＋（rest−300万円）
    （＝収入金額から300万円に控除額を加算した金額を控除した残額と150万円との合計額）。"""
    if rest <= r.short_split:
        return _half_part(rest, r)
    return r.short_base + rest - r.short_split


def retirement_income_multi(general: int, short: int, officer: int, total_ded: int, short_ded: int, officer_ded: int, r: RetirementRules) -> Fraction:
    """その年中に一般・短期・特定役員の退職手当等のうち二以上がある場合の退職所得の金額（所法30⑦、所令71の2①③⑤⑦⑨）。

    total_ded は退職所得控除額（所法30②：⑥の調整の後）。short_ded・officer_ded は短期退職所得控除額（①一イ・⑦二イ）・特定役員退職所得控除額
    （③一・⑤一・⑦一）。一般退職所得控除額と、⑤の短期退職所得控除額は total_ded から引いた残額としてここで求める。
    1円未満は丸めない（Fraction。呼び出し側が根拠のない端数の候補で丸める）。
    """
    if sum(1 for a in (general, short, officer) if a > 0) < 2:
        raise ValueError("二以上の区分の退職手当等がない")
    F = Fraction
    if officer == 0:  # ① 一般＋短期
        gen_ded = total_ded - short_ded
        rest_s = F(short - short_ded - max(0, gen_ded - general))
        rest_g = F(general - gen_ded - max(0, short_ded - short))
        return _short_part(rest_s, r) + _half_part(rest_g, r)
    if short == 0:  # ③ 一般＋特定役員
        gen_ded = total_ded - officer_ded
        rest_o = F(officer - officer_ded - max(0, gen_ded - general))
        rest_g = F(general - gen_ded - max(0, officer_ded - officer))
        return max(F(0), rest_o) + _half_part(rest_g, r)
    if general == 0:  # ⑤ 短期＋特定役員
        sd = total_ded - officer_ded
        rest_o = F(officer - officer_ded - max(0, sd - short))
        rest_s = F(short - sd - max(0, officer_ded - officer))
        return max(F(0), rest_o) + _short_part(rest_s, r)
    # ⑦ 三つとも（⑨：満たない部分を他の2つの残額から2分の1ずつ控除し、一方が2分の1に満たなければその不足を他方に加える）
    gen_ded = total_ded - officer_ded - short_ded
    rest_o = F(officer - officer_ded)
    raw_s = F(short - short_ded)
    over = raw_s > r.short_split  # ⑦二 イかロか
    rest_s = raw_s - r.short_split if over else raw_s  # ⑨の「第七項第二号イ又はロの残額」
    rest_g = F(general - gen_ded)

    def take(lack: Fraction, a: Fraction, b: Fraction) -> tuple[Fraction, Fraction]:
        half = lack / 2
        da = half + max(F(0), half - max(F(0), b))
        db = half + max(F(0), half - max(F(0), a))
        return a - da, b - db

    if officer < officer_ded:
        rest_s, rest_g = take(F(officer_ded - officer), rest_s, rest_g)
    if short < short_ded:
        rest_o, rest_g = take(F(short_ded - short), rest_o, rest_g)
    if general < gen_ded:
        rest_o, rest_s = take(F(gen_ded - general), rest_o, rest_s)
    short_part = (r.short_base + max(F(0), rest_s)) if over else _half_part(rest_s, r)
    return max(F(0), rest_o) + short_part + _half_part(rest_g, r)


# ---------------------------------------------------------------------------
# 家内労働者等の必要経費の特例（租税特別措置法第27条、同施行令第18条の2第2項）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expenses:
    """事業所得・業務に係る雑所得の必要経費（特例の後）と、特例を当てたか。"""

    business: int
    misc: int
    special_applied: bool


def home_worker_expenses(
    business_revenue: int, business_expense: int, misc_revenue: int, misc_expense: int, amount: int, is_home_worker: bool
) -> Expenses:
    """措法27・措令18の2②：家内労働者等で、事業所得と雑所得の必要経費の合計が特例の額に満たないときの必要経費。

    - 事業所得だけ・雑所得だけ（措令18の2②一）：特例の額（その所得の総収入金額が限度）。
    - 両方（同二）：イ（事業所得）＝特例の額のうち事業所得の必要経費に達するまでの部分（雑所得の総収入金額がロに満たなければ、
      満たない部分を加えた額）、ロ（雑所得）＝特例の額のうちイ以外の部分。それぞれ総収入金額が限度（措法27 後段）。
    給与所得を有する人は amount に「特例の額 − 給与所得控除額（給与等の収入金額を限度：国税庁の計算書の読み）」を渡す（variables.home_worker_amounts）。
    事業所得と雑所得の両方があって事業所得が赤字になる人（実額の必要経費＞事業所得の総収入金額）で、雑所得の総収入金額が
    ロの額（特例の額−事業所得の必要経費：計算書の⑤）を超えるときは、国税庁の計算書の⑧（事業所得の必要経費＝特例適用前の必要経費②）で計算する。
    措法27 後段（総収入金額を限度）・措令18の2②二の文言では事業所得の必要経費は総収入金額までになり食い違うが、公式の説明（計算書）があり
    反対の一次情報がないので、D22 S1 により計算書の読みで計算し根拠に「法令の読み」を付ける（basis.HOME_WORKER_DEFICIT。
    jigyo-laws-and-nta §2.3。書き方 §2.4 は赤字の人に税務署に尋ねるよう書く）。
    雑所得の総収入金額は業務に係るもの（公的年金等に係るものを除く。その他の雑所得は income_kinds の未実装の約束）。
    """
    if not is_home_worker or business_expense + misc_expense >= amount:
        return Expenses(business_expense, misc_expense, False)
    if business_revenue <= 0 and misc_revenue <= 0:
        return Expenses(business_expense, misc_expense, False)
    if misc_revenue <= 0:
        return Expenses(min(amount, business_revenue), misc_expense, True)
    if business_revenue <= 0:
        return Expenses(business_expense, min(amount, misc_revenue), True)
    ro = amount - business_expense  # 事業所得の必要経費（< 特例の額）に達するまでの部分以外（計算書の⑤）
    if business_expense > business_revenue and misc_revenue > ro:
        return Expenses(business_expense, ro, True)  # 計算書の⑧（②）と⑨（③と⑤の少ない方＝⑤）
    i = business_expense + max(0, ro - misc_revenue)
    return Expenses(min(i, business_revenue), min(ro, misc_revenue), True)


# ---------------------------------------------------------------------------
# 青色申告特別控除（租税特別措置法第25条の2。令和7年分・令和8年分の形）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlueRules:
    basic: int
    full: int
    etax: int


def blue_rules(p: Any) -> BlueRules:
    n = p.所得税.青色申告特別控除
    return BlueRules(_int(n.第1項の額, "第1項の額"), _int(n.第3項の額, "第3項の額"), _int(n.第4項の額, "第4項の額"))


def blue_deduction(approved: bool, income_before: int, bookkeeping: bool, filing: str, r: BlueRules) -> int:
    """青色申告特別控除額（事業所得から控除する額）。

    - 承認がなければ0。
    - 第3項（55万円）：事業所得を生ずべき事業（判断.事業と称するに至る程度で事業所得に区分した業務）・正規の簿記（措規9の6①）・
      第6項（期限内の申告に控除の記載と貸借対照表・損益計算書の添付）。第4項第2号（e-Tax で期限内に送信）なら65万円。
      第4項第1号（優良な電子帳簿で備え付け・保存し届出をした書面の申告：FILING_EBOOKS）も65万円。
    - それ以外は第1項（10万円）。
    - 限度は事業所得の金額（損益通算の前の黒字。措通25の2−1）。不動産所得がある人は入力の段で対象外（不動産所得から順次控除：
      第2項・第5項。不動産所得は income_kinds の未実装の約束）。
    """
    if not approved or income_before <= 0:
        return 0
    if filing not in FILING_KINDS:
        raise ValueError(f"申告の要件の区分が不明: {filing!r}")
    if bookkeeping and filing in (FILING_ETAX, FILING_EBOOKS):
        amount = r.etax
    elif bookkeeping and filing == FILING_PAPER:
        amount = r.full
    else:
        amount = r.basic
    return min(amount, income_before)


def blue_deduction_split(
    approved: bool, real_estate_before: int, business_before: int, bookkeeping: bool, filing: str, r: BlueRules
) -> tuple[int, int, int]:
    """青色申告特別控除の総額と、不動産所得・事業所得からの控除額（措法25の2②⑤：不動産所得の金額、事業所得の金額の順に控除）。

    限度は「黒字の所得の合計」（TA2072（注2）：いずれかが赤字ならないものとして合計する。fudosan §3.4）。
    """
    positive = max(0, real_estate_before) + max(0, business_before)
    total = blue_deduction(approved, positive, bookkeeping, filing, r)
    to_real_estate = min(total, max(0, real_estate_before))
    return total, to_real_estate, total - to_real_estate


# ---------------------------------------------------------------------------
# 不動産所得の損失の通算の制限（措法41の4、所法69②）
# ---------------------------------------------------------------------------


def rental_loss_excluded(loss_before: int, land_interest: int, all_villa: bool, villa_loss: int = 0) -> int:
    """不動産所得の損失のうち、損益通算の上で生じなかったものとみなす金額。

    損失（loss_before < 0）のとき：土地等を取得するために要した負債の利子の額に相当する部分は生じなかったものとみなす
    （措法41の4①、措令26の6①：利子の額が損失の金額を超えるときは損失の金額、それ以外は利子の額）。別荘等の貸付けだけの損失は
    全額（所法69②、所令178①二：TA1391）。別荘等とそれ以外の貸付けがともに損失のときは、別荘等の貸付けの損失の額（villa_loss。入力の段で物件ごとの
    収支から求める。土地等の負債の利子と重なるときは入力の段で分かれ目にするので、ここでは足すだけ）。国外中古建物・組合事業は入力の段で対象外。
    """
    if loss_before >= 0:
        return 0
    loss = -loss_before
    if all_villa:
        return loss
    return min(loss, max(0, land_interest) + max(0, villa_loss))


__all__ = [
    "BLUE_APPROVED",
    "BLUE_NOT_APPROVED",
    "BlueRules",
    "Expenses",
    "FILING_EBOOKS",
    "FILING_ETAX",
    "FILING_KINDS",
    "FILING_OTHER",
    "FILING_PAPER",
    "PensionRules",
    "RETIRE_GENERAL",
    "RETIRE_KINDS",
    "RETIRE_OFFICER",
    "RETIRE_SHORT",
    "RetirementRules",
    "DEPRECIATION_CEIL",
    "PENSION_FLOOR",
    "blue_deduction",
    "blue_deduction_split",
    "rental_loss_excluded",
    "blue_rules",
    "home_worker_expenses",
    "pension_deduction",
    "pension_deduction_yen",
    "pension_income",
    "pension_rules",
    "retirement_deduction",
    "retirement_has_fraction",
    "retirement_income",
    "retirement_rules",
    "windfall_income",
]

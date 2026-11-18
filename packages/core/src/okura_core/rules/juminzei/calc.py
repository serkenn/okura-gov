"""規則モジュール juminzei の計算の純粋関数（OpenFisca の式とテストの両方が使う）。

金額は整数の円、途中の値は Fraction（D21 R5。packages/core/README.md §5）。法令が丸めを定める箇所（課税標準額の千円未満、
確定金額の百円未満、配偶者特別控除の1万円未満の切上げ）でだけ丸める。根拠のない1円未満は呼び出し側が候補の丸めを渡す。
法令の値は parameters/ にだけ置き、ここはパラメータの節（OpenFisca の ParameterNodeAtInstant）から読む。

所得割の税額の連鎖（docs/hypotheses/20261109_round2_juminzei-tax-calc-model.md H1・H8、docs/hypotheses/20261109_round3_juminzei-extra-model.md H4-3）：
  市町村民税・道府県民税ごとに
  算出所得割（課税総所得金額等×税率＋分離課税の上場株式等×率）→ 調整控除（第314条の6）→ 配当控除・住宅借入金等特別税額控除・寄附金税額控除
  （いずれも調整控除の後の額を基にする。互いの順序は結果に効かない）→ 所得割の非課税の境目の調整（附則第3条の3第5項）→ 申告特例控除
  （附則第7条の2：寄附金税額控除の後）→ 配当割額等の控除（第314条の9：最後。引ききれない額は控除不足額）→ 百円未満切捨て（第20条の4の2第3項）。
  寄附金の合計額は市町村民税・道府県民税で別（第2号〜第4号は団体ごとの条例）。特例控除の割合は附則第5条の5（分離課税の所得がある場合）を当てる。
  均等割の税率が百円の倍数でない団体では、均等割と合わせた確定金額の切捨ての差を均等割の側に置く（per_capita_with_income_levy）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

Rounder = Callable[[int | Fraction], int]
ZERO = Fraction(0)

#: 住民税_賦課期日に住所を有する市町村 の「住所がない」の値（2026-11-12。以前は空の文字列で、結果の区分の値〔空でない文字列〕にできず、
#: 賦課期日の前に死亡した人がいる中間表現〔例 08〕の評価が止まっていた）
NO_DOMICILE = "なし"


def has_domicile(code: Any) -> bool:
    """賦課期日に住所を有する市町村の値（団体コードか NO_DOMICILE）が住所を表すか。"""
    return bool(code) and code != NO_DOMICILE


def _r(node: Any) -> Fraction:
    """パラメータの節（分子・分母）を率にする。"""
    return Fraction(int(node.分子), int(node.分母))


def floor_unit(x: int | Fraction, unit: int) -> int:
    """unit 円未満を切り捨てる（0未満は0にしてから。課税標準額・確定金額は負にならない）。"""
    if x <= 0:
        return 0
    return math.floor(Fraction(x) / unit) * unit


#: 課税標準額の千円未満の切捨ての当て先の読み（JM-22・JT1。ReadingSlotSpec の候補の名前。最初が既定）
READING_AFTER_DEDUCTION = "控除後の課税総所得金額等"
READING_BEFORE_DEDUCTION = "控除前の総所得金額"
TAXABLE_READINGS = (READING_AFTER_DEDUCTION, READING_BEFORE_DEDUCTION)


def taxable_floor_before_deduction(total: int, deductions: int, unit: int) -> int:
    """控除前の総所得金額（第313条の課税標準）に千円未満の切捨てを当て、所得控除を引いた額（0未満は0）。JT1 のもう一つの読み。"""
    return max(floor_unit(total, unit) - deductions, 0)


# ---------------------------------------------------------------------------
# 所得控除（地方税法第314条の2）
# ---------------------------------------------------------------------------


def basic_deduction(total_income: int, p: Any) -> int:
    """基礎控除の額（第2項）：前年の合計所得金額の区分。"""
    for key in ("第1号", "第2号", "第3号"):
        node = p[key]
        if total_income <= int(node.上限):
            return int(node.額)
    return 0


def spouse_deduction(own_income: int, elderly: bool, p: Any) -> int:
    """配偶者控除の額（第10号）：控除対象配偶者を有する納税義務者の前年の合計所得金額の区分。1,000万円を超えれば0。"""
    tiers = p.本人の区分
    table = p.老人の額 if elderly else p.額
    for i, key in enumerate(("第1号の上限", "第2号の上限", "第3号の上限")):
        if own_income <= int(tiers[key]):
            return int(table[("第1号", "第2号", "第3号")[i]])
    return 0


def round_down_to_step(x: int, step: int, minus: int) -> int:
    """「step の整数倍の金額から minus を控除した金額」で x を超えないもののうち最も多い金額（x がその形ならそのまま）。"""
    return ((x + minus) // step) * step - minus


def spouse_special_deduction(own_income: int, spouse_income: int, p: Any) -> int:
    """配偶者特別控除の額（第10号の2）。配偶者の前年の合計所得金額の区分（イ（１）〜（３））と、本人の区分（イ・ロ・ハ）。

    イ（２）：38万円 −（配偶者の所得のうち 93万1円を超える部分を「5万円の整数倍−3万円」に切り下げた額）。
    ロ・ハ：イの額の 2/3・1/3（1万円未満の端数は切上げ）。本人が 1,000万円超・配偶者が 133万円超なら0。
    """
    if spouse_income > int(p.配偶者の合計所得金額の上限):
        return 0
    if spouse_income <= int(p.イ.上限):
        base = int(p.イ.額)
    elif spouse_income <= int(p.ロ.上限):
        exceed = spouse_income - int(p.ロ.超える部分の起点)
        base = int(p.ロ.基準の額) - round_down_to_step(exceed, int(p.ロ.刻み), int(p.ロ.刻みから引く額))
    else:
        base = int(p.ハ.額)
    tiers = p.本人の区分
    unit = int(p.切上げの単位)
    if own_income <= int(tiers.第1号の上限):
        return base
    if own_income <= int(tiers.第2号の上限):
        return math.ceil(Fraction(base) * _r(p.ロの率) / unit) * unit
    if own_income <= int(tiers.第3号の上限):
        return math.ceil(Fraction(base) * _r(p.ハの率) / unit) * unit
    return 0


def specified_relative_amount(income: int, p: Any) -> int:
    """特定親族特別控除の、特定親族1人の額（第12号イ〜ニ。段の表）。"""
    for i in range(1, 8):
        node = p[f"第{i}段"]
        if income <= int(node.上限):
            return int(node.額)
    return 0


@dataclass(frozen=True)
class Stage:
    """段階の式の1段：x が at_most 以下なら base ＋（x − minus）× ratio。at_most が None なら最後の段（base）。"""

    at_most: int | None
    base: int
    minus: int
    ratio: Fraction


def staged(x: int, steps: Sequence[Stage]) -> Fraction:
    for s in steps:
        if s.at_most is None or x <= s.at_most:
            return Fraction(s.base) + (Fraction(x) - s.minus) * s.ratio
    raise ValueError("段階の式の最後の段がない")


def life_steps(node: Any) -> tuple[Stage, ...]:
    """生命保険料控除の段（第1段は全額、第2段は加算額＋1/2、第3段は加算額＋1/4、最後は最高額）。"""
    one, two, three = int(node.第1段の上限), int(node.第2段の上限), int(node.第3段の上限)
    return (
        Stage(one, 0, 0, Fraction(1)),
        Stage(two, int(node.第2段の加算額), one, Fraction(1, 2)),
        Stage(three, int(node.第3段の加算額), two, Fraction(1, 4)),
        Stage(None, int(node.最高額), 0, ZERO),
    )


#: 新旧の選択（中間表現の 選択.保険料控除の区分 の life_insurance_regime。所得税と同じ1つの選択を当てる）。
REGIMES = ("new_only", "old_only", "both")


def life_insurance_exact(
    new_life: int, old_life: int, care: int, new_annuity: int, old_annuity: int, regime: str, p: Any
) -> tuple[Fraction, Fraction, Fraction]:
    """生命保険料控除の区分ごとの額（丸める前の有理数）：一般・介護医療・個人年金（第314条の2第1項第5号イ〜ハ）。"""
    if regime not in REGIMES:
        raise ValueError(f"生命保険料の新旧の選択として知らない値: {regime!r}")
    new_s, old_s = life_steps(p.新), life_steps(p.旧)
    both_cap = int(p.新旧合計の上限)

    def pair(new: int, old: int) -> Fraction:
        n = new if regime in ("new_only", "both") else 0
        o = old if regime in ("old_only", "both") else 0
        a = staged(n, new_s) if n > 0 else ZERO
        b = staged(o, old_s) if o > 0 else ZERO
        if n > 0 and o > 0:
            return min(a + b, Fraction(both_cap))
        return a + b

    return pair(new_life, old_life), (staged(care, new_s) if care > 0 else ZERO), pair(new_annuity, old_annuity)


def life_insurance_deduction(parts: tuple[Fraction, Fraction, Fraction], rounder: Rounder, p: Any) -> int:
    """生命保険料控除の額：区分ごとの額の1円未満は rounder（根拠なし：候補で評価）、合計の上限 7万円。"""
    return min(sum(rounder(x) for x in parts), int(p.合計の上限))


def earthquake_exact(quake: int, old_long: int, p: Any) -> Fraction:
    """地震保険料控除の額（丸める前）：地震保険料の1/2（上限 2万5千円）、旧長期損害保険料（最高1万円）、両方なら合計 2万5千円。"""
    a = min(Fraction(quake) * _r(p.率), Fraction(int(p.上限))) if quake > 0 else ZERO
    ol = p.旧長期
    if old_long <= 0:
        b = ZERO
    elif old_long <= int(ol.全額の上限):
        b = Fraction(old_long)
    else:
        b = int(ol.加算額) + Fraction(min(old_long - int(ol.全額の上限), int(ol.超える額の上限))) * _r(p.率)
    if quake > 0 and old_long > 0:
        return min(a + b, Fraction(int(p.合計の上限)))
    return a + b


def medical_deduction(expense: int, total_income: int, rounder: Rounder, p: Any) -> int:
    """医療費控除の額（第314条の2第1項第2号）：補塡後の医療費 − min(前年の総所得金額等×5%〔1円未満は rounder〕, 10万円)、0〜200万円。"""
    if expense <= 0:
        return 0
    five = rounder(Fraction(max(total_income, 0)) * _r(p.率))
    return min(max(expense - min(five, int(p.足切りの上限)), 0), int(p.上限))


def medical_fraction_matters(expense: int, total_income: int, p: Any) -> bool:
    five = Fraction(max(total_income, 0)) * _r(p.率)
    return expense > 0 and five.denominator != 1 and five < int(p.足切りの上限) and expense > math.floor(five)


def casualty_deduction(loss: int, related: int, total_income: int, rounder: Rounder, p: Any) -> int:
    """雑損控除の額（第314条の2第1項第1号。所得税法第72条と同じ形）：損失の金額 − 足切りの額（総所得金額等の1/10 など）。"""
    if loss <= 0:
        return 0
    tenth = rounder(Fraction(max(total_income, 0)) * _r(p.率))
    limit = int(p.災害関連支出の足切り)
    if related <= limit:
        threshold = tenth
    elif related < loss:
        threshold = min(loss - (related - limit), tenth)
    else:
        threshold = min(limit, tenth)
    return max(loss - threshold, 0)


def casualty_fraction_matters(loss: int, total_income: int, p: Any) -> bool:
    tenth = Fraction(max(total_income, 0)) * _r(p.率)
    return loss > 0 and tenth.denominator != 1 and loss > math.floor(tenth)


# ---------------------------------------------------------------------------
# 非課税（第295条、附則第3条の3、施行令第47条の3、森林環境税法施行令第1条）
# ---------------------------------------------------------------------------


def exemption_line(count: int, per_person: int, fixed: int, with_dependents: int) -> int:
    """非課税の基準の額：per_person ×（同一生計配偶者及び扶養親族の数＋1）＋ fixed（数が1以上なら＋with_dependents）。"""
    return per_person * (count + 1) + fixed + (with_dependents if count > 0 else 0)


# ---------------------------------------------------------------------------
# 調整控除（第314条の6・第37条）
# ---------------------------------------------------------------------------


def adjustment_base(personal_diff: int, taxable: int, total_income: int, p: Any) -> int:
    """調整控除の率を乗じる額（市町村民税・道府県民税で同じ）。前年の合計所得金額が 2,500万円超、合計課税所得金額が0なら0。

    200万円以下：min(人的控除差の合計, 合計課税所得金額)、200万円超：max(人的控除差の合計 −（合計課税所得金額 − 200万円）, 5万円)。
    """
    if total_income > int(p.合計所得金額の上限) or taxable <= 0:
        return 0
    line = int(p.合計課税所得金額の基準)
    if taxable <= line:
        return min(personal_diff, taxable)
    return max(personal_diff - (taxable - line), int(p.最低の額))


# ---------------------------------------------------------------------------
# 配当控除（附則第5条）
# ---------------------------------------------------------------------------


def dividend_split(surplus: int, trust: int, foreign: int, taxable_total: int, line: int) -> dict[str, tuple[int, int]]:
    """配当所得の金額を、課税総所得金額等の 1,000万円以下の部分（高い率）と超える部分（低い率）に分ける。

    課税総所得金額等（T）が 1,000万円以下なら全部が高い率。超えるときは、証券投資信託（一般外貨建等を含む：S）を T の上積み、
    剰余金の配当等（D）をその下に置く（T − S が 1,000万円を超える部分の D が低い率）。所得税法第92条第1項第2号・第3号と同じ区分の読み
    （住民税の表の「課税総所得金額（から証券投資信託の配当所得を除いた額）」：docs/public-sources/20261109_round2_juminzei-tax-law-text.md §6）。
    戻り値：区分 → (高い率の部分, 低い率の部分)。
    """
    s = trust + foreign
    over = max(taxable_total - line, 0)
    low_s = min(s, over)
    low_d = min(surplus, max(taxable_total - s - line, 0))
    # 証券投資信託の低い率の部分は、外貨建等を上に置く（率の低いものほど上積み）
    low_f = min(foreign, low_s)
    low_t = low_s - low_f
    return {
        "剰余金の配当等": (surplus - low_d, low_d),
        "証券投資信託": (trust - low_t, low_t),
        "一般外貨建等証券投資信託": (foreign - low_f, low_f),
    }


def dividend_credit(split: dict[str, tuple[int, int]], node: Any, entity: str) -> Fraction:
    """配当控除の額（丸める前）：区分ごとに 高い率の部分×高い率 ＋ 低い率の部分×低い率。entity は 市町村民税・道府県民税・指定都市の…。"""
    den = int(node.率の分母)
    total = ZERO
    for cls, (hi, lo) in split.items():
        r = node[cls][entity]
        total += Fraction(hi * int(r.高い率) + lo * int(r.低い率), den)
    return total


# ---------------------------------------------------------------------------
# 寄附金税額控除・特例控除・申告特例控除（第314条の7、附則第5条の6・第7条の2・第7条の3）
# ---------------------------------------------------------------------------


def special_ratio(taxable: int, adjust: int, p: Any) -> Fraction:
    """特例控除額の割合（第314条の7第11項第1号・第2号、附則第5条の6第2項の読替え）。

    課税総所得金額 − 人的控除差調整額 が0以上なら区分の表、0未満なら 90%（課税山林・課税退職所得金額がない場合：この版では常にない）。
    """
    den = int(p.特例控除の割合の分母)
    x = taxable - adjust
    if x < 0:
        return Fraction(int(p.第2号の割合), den)
    t = p.特例控除の割合
    for i in range(1, 7):
        node = t[f"第{i}段"]
        if x <= int(node.上限):
            return Fraction(int(node.割合), den)
    return Fraction(int(t.第7段.割合), den)


def special_ratio_with_separate(taxable: int, adjust: int, separate_income: bool, p: Any) -> Fraction:
    """特例控除額の割合に附則第5条の5（市町村民税は第2項、道府県民税は第1項）を当てたもの。

    第314条の7第11項第2号・第3号に当たる場合（課税総所得金額−人的控除差調整額が0未満。課税山林・課税退職所得金額はこの版では常にない）又は
    課税総所得金額等を有しない場合で、上場株式等の分離課税（附則第33条の2第5項・第35条の2の2第5項）の適用を受けるときは、第5号の割合
    （100分の75。附則第5条の6 の読替えで 74.685%）。第1号〜第4号はこの版では当たらない（山林・退職・土地等・短期譲渡の分離課税の所得が常に0）ので
    「最も低い割合」は第5号の割合（docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md §2、
    docs/public-sources/20261109_round2_juminzei-tax-law-text.md §8.2）。上限（所得割の額の20%）と按分（5分の3・5分の4）は第11項と同じ。
    """
    if separate_income and taxable - adjust < 0:
        return Fraction(int(p.分離課税の所得がある場合の割合), int(p.特例控除の割合の分母))
    return special_ratio(taxable, adjust, p)


def filing_special_ratio(taxable: int, adjust: int, p: Any) -> Fraction:
    """申告特例控除額の割合（附則第7条の2第5項、附則第7条の3第2項の読替え）。区分の基準が0未満のときは表の最初の行（195万円以下）を使う
    （直接定めた文言がない：docs/public-sources/20261109_round2_juminzei-tax-law-text.md §8.3。法令の読み）。"""
    x = taxable - adjust
    for i in range(1, 5):
        node = p[f"第{i}段"]
        if x <= int(node.上限):
            return Fraction(int(node.分子), int(node.分母))
    return Fraction(int(p.第5段.分子), int(p.第5段.分母))


# ---------------------------------------------------------------------------
# 所得割の税額の連鎖
# ---------------------------------------------------------------------------

ENTITIES = ("市町村民税", "道府県民税")


@dataclass(frozen=True)
class ChainInput:
    """1人の所得割の計算に使う値（整数の円・率・真偽）。"""

    taxable: int  # 課税総所得金額等（千円未満切捨て後）
    taxable_dividend: int  # 上場株式等に係る課税配当所得等の金額（分離課税）
    taxable_gain: int  # 上場株式等に係る課税譲渡所得等の金額（分離課税）
    total_income: int  # 前年の合計所得金額（調整控除の 2,500万円）
    gross_income: int  # 前年の総所得金額等（寄附金の 30%、附則第3条の3）
    personal_diff: int  # 人的控除差の合計（調整控除の表の 5万円＋…）
    personal_adjust: int  # 人的控除差調整額（寄附金・申告特例：人的控除差の合計＋基礎控除の差）
    surplus_dividend: int  # 配当控除の対象の剰余金の配当等に係る配当所得
    trust_dividend: int  # 証券投資信託
    foreign_dividend: int  # 一般外貨建等証券投資信託
    housing_credit: int  # 前年分の所得税の住宅借入金等特別税額控除額（①：外部の値）
    income_tax_before: int  # 前年分の所得税の額（②：住宅借入金等特別控除などの前）
    housing_base: int  # 控除限度の基（前年分の所得税の課税総所得金額等〔＋基礎控除の差〕）
    donation_total: int  # 寄附金税額控除の対象の寄附金の合計
    special_donation: int  # 特例控除対象寄附金の合計
    filing_special: bool  # 申告特例控除の対象か
    withheld_local: int  # 控除の対象の配当割額・株式等譲渡所得割額
    exemption_line: int  # 所得割の非課税の基準の額（附則第3条の3第4項）
    designated: bool  # 指定都市の区域内に住所を有するか
    rate_m: Fraction  # 市町村民税の所得割の税率（注入）
    rate_p: Fraction  # 道府県民税の所得割の税率（注入）
    donation_extra_m: int = 0  # 第314条の7第1項第2号〜第4号の寄附金（市町村民税：共同募金会・日赤・市町村の条例で定めるもの）
    donation_extra_p: int = 0  # 第37条の2第1項第2号〜第4号の寄附金（道府県民税：共同募金会・日赤・道府県の条例で定めるもの）
    housing_specified: bool = False  # 居住年が平成26年〜令和3年で特定取得・特別特定取得の住宅借入金等がある（附則第5条の4第7項・第3項）
    separate_income: bool = False  # 上場株式等の分離課税（附則第33条の2第5項・第35条の2の2第5項）の適用を受ける（附則第5条の5）


@dataclass(frozen=True)
class EntityResult:
    computed: Fraction  # 算出所得割（第314条の3＋分離課税）
    adjustment: Fraction  # 調整控除（第314条の6。算出所得割を限度）
    dividend: Fraction  # 配当控除
    housing: Fraction  # 住宅借入金等特別税額控除
    donation: Fraction  # 寄附金税額控除（基本控除＋特例控除。所得割を限度）
    border: Fraction  # 所得割の非課税の境目の調整（附則第3条の3第5項）
    filing_special: Fraction  # 申告特例控除
    withheld: Fraction  # 配当割額等の控除（控除できた額）
    shortfall: Fraction  # 配当割額等の控除しきれなかった額
    final: int  # 所得割の額（百円未満切捨て）
    fraction: int = 0  # 所得割の額の百円未満の部分（1円未満切捨て。均等割と合わせた確定金額の切捨てに使う：per_capita_with_income_levy）


@dataclass(frozen=True)
class ChainResult:
    municipal: EntityResult
    prefectural: EntityResult

    def total(self, field: str) -> Fraction:
        return Fraction(getattr(self.municipal, field)) + Fraction(getattr(self.prefectural, field))


@dataclass(frozen=True)
class ChainRules:
    """税額の連鎖に使うパラメータの節（parameters(period).住民税 の下）。"""

    adjust: Any  # 調整控除
    credits: Any  # 税額控除
    rates: Any  # 税率


def _entity_key(entity: str, designated: bool) -> str:
    return f"指定都市の{entity}" if designated else entity


def compute_chain(x: ChainInput, rules: ChainRules) -> ChainResult:
    """所得割の額の連鎖（このファイルの先頭の説明）。途中は有理数、最後に市町村民税・道府県民税ごとに百円未満切捨て。"""
    c = rules.credits
    adjust_base = adjustment_base(x.personal_diff, x.taxable, x.total_income, rules.adjust)
    split = dividend_split(x.surplus_dividend, x.trust_dividend, x.foreign_dividend, x.taxable + x.taxable_dividend + x.taxable_gain, int(c.配当控除.基準))
    housing_diff = max(x.housing_credit - x.income_tax_before, 0)
    k = c.寄附金税額控除
    cap30 = Fraction(max(x.gross_income, 0)) * _r(k.総所得金額等の上限の率)
    donation_capped = {
        "市町村民税": min(Fraction(x.donation_total + x.donation_extra_m), cap30),
        "道府県民税": min(Fraction(x.donation_total + x.donation_extra_p), cap30),
    }
    footing = int(k.足切り)
    special_base = max(x.special_donation - footing, 0)
    ratio = special_ratio_with_separate(x.taxable, x.personal_adjust, x.separate_income, k)
    filing_ratio = filing_special_ratio(x.taxable, x.personal_adjust, c.申告特例控除.割合)
    unit = int(rules.rates.端数.確定金額の単位)
    stages: dict[str, dict[str, Fraction]] = {}
    for entity in ENTITIES:
        key = _entity_key(entity, x.designated)
        rate = x.rate_m if entity == "市町村民税" else x.rate_p
        sep = _r(rules.rates.分離課税.上場株式等[key])
        computed = Fraction(x.taxable) * rate + Fraction(x.taxable_dividend + x.taxable_gain) * sep
        adjustment = min(Fraction(adjust_base) * _r(rules.adjust.率[key]), computed)
        base = computed - adjustment
        dividend = dividend_credit(split, c.配当控除, key) if any(v != (0, 0) for v in split.values()) else ZERO
        h = c.住宅借入金等特別税額控除
        housing = ZERO
        if housing_diff > 0:
            lr, lc = (h.特定取得の控除限度の率, h.特定取得の控除限度の上限) if x.housing_specified else (h.控除限度の率, h.控除限度の上限)
            limit = min(Fraction(max(x.housing_base, 0)) * _r(lr[key]), Fraction(int(lc[key])))
            housing = min(Fraction(housing_diff) * _r(h.按分[key]), limit)
        donation = ZERO
        if donation_capped[entity] > footing:
            donation = (donation_capped[entity] - footing) * _r(k.基本控除の率[key])
        special = ZERO
        if special_base > 0:
            # 特例控除額（第11項）：調整控除の後の所得割の額の 20% を限度（令和9年度分までは定額の上限なし）
            special = min(Fraction(special_base) * ratio * _r(k.特例控除の按分[key]), base * _r(k.特例控除の上限の率))
        donation = min(donation + special, base)
        # 表示のために控除できた額を行政の案内の順（配当控除 → 住宅借入金等 → 寄附金）で割り当てる。最終の額は順によらない（H8）
        rest = base
        used_dividend = min(dividend, rest)
        rest -= used_dividend
        used_housing = min(housing, rest)
        rest -= used_housing
        used_donation = min(donation, rest)
        rest -= used_donation
        stages[entity] = {
            "computed": computed,
            "adjustment": adjustment,
            "dividend": used_dividend,
            "housing": used_housing,
            "donation": used_donation,
            "special": special,
            "after": rest,
        }
    # 附則第3条の3第5項：B・C は第314条の3、第314条の6〜第314条の8、附則第5条第3項・第5条の4第5項を適用した所得割の額
    after = {e: s["after"] for e, s in stages.items()}
    b, cc = after["市町村民税"], after["道府県民税"]
    border = {e: ZERO for e in ENTITIES}
    excess = Fraction(x.exemption_line) - (Fraction(x.gross_income) - (b + cc))
    if excess > 0 and b + cc > 0:
        border["市町村民税"] = min(excess * b / (b + cc), b)
        border["道府県民税"] = min(excess * cc / (b + cc), cc)
    results: dict[str, EntityResult] = {}
    for entity in ENTITIES:
        s = stages[entity]
        rest = after[entity] - border[entity]
        filing = ZERO
        if x.filing_special and special_base > 0:
            filing = min(s["special"] * filing_ratio, rest)
        rest -= filing
        share = _r(c.配当割額等の控除[entity])
        claim = Fraction(x.withheld_local) * share
        used = min(claim, rest)
        rest -= used
        results[entity] = EntityResult(
            computed=s["computed"],
            adjustment=s["adjustment"],
            dividend=s["dividend"],
            housing=s["housing"],
            donation=s["donation"],
            border=border[entity],
            filing_special=filing,
            withheld=used,
            shortfall=claim - used,
            final=floor_unit(rest, unit),
            fraction=levy_fraction(rest, unit),
        )
    return ChainResult(results["市町村民税"], results["道府県民税"])


# ---------------------------------------------------------------------------
# 均等割と所得割を合わせた確定金額の百円未満の切捨て（第294条第1項第1号・第20条の4の2第3項）
# ---------------------------------------------------------------------------


def levy_fraction(rest: Fraction | int, unit: int) -> int:
    """所得割の額（百円未満を切り捨てる前の有理数）の、百円未満の部分の1円未満を切り捨てた額（0〜unit−1）。"""
    if rest <= 0:
        return 0
    return math.floor(Fraction(rest) - floor_unit(rest, unit))


def per_capita_with_income_levy(rate: int, fraction: int, unit: int) -> int:
    """住所地の市町村民税（道府県民税）の均等割の側の額：floor100(所得割＋均等割) − floor100(所得割)。

    住所を有する者の市町村民税は均等割額と所得割額の合算額で課し（第294条第1項第1号・第24条第1項第1号）、確定金額の百円未満を切り捨てる
    （第20条の4の2第3項）。所得割の額は百円未満を切り捨てて示すので、合算額の切捨ての差を均等割の側に置く。fraction は所得割の百円未満の部分
    （levy_fraction。所得割を課さない者は0）。均等割の税率が百円の倍数なら rate のまま。
    """
    if rate <= 0:
        return 0
    return floor_unit(fraction + rate, unit)


# ---------------------------------------------------------------------------
# 団体コード（総務省「全国地方公共団体コード仕様」3・5・6）
# ---------------------------------------------------------------------------


def check_digit(five: str) -> int:
    """第1桁〜第5桁に 6・5・4・3・2 を乗じた積の和を11で割った余りと11の差の下1桁（積の和が11未満なら 11−積の和）。

    docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md §4。積の和が1（11−積の和が10）の場合は仕様に書かれていない
    （docs/measurements/20261111_impl-research3_all-fetch-and-checks.md §5）ので誤りにする。
    """
    if len(five) != 5 or not five.isdigit():
        raise ValueError(f"団体コードの第1桁〜第5桁でない: {five!r}")
    total = sum(int(d) * w for d, w in zip(five, (6, 5, 4, 3, 2)))
    if total < 11:
        if 11 - total >= 10:
            raise ValueError(f"検査数字が仕様で決まらない: {five!r}")
        return 11 - total
    return (11 - total % 11) % 10


def prefecture_code(municipality_code: str) -> str:
    """市町村の団体コード（6桁）から、その市町村の属する都道府県の団体コード（第1・2桁＋000＋検査数字。仕様 5.2・6.1）。"""
    if len(municipality_code) != 6 or not municipality_code.isdigit():
        raise ValueError(f"団体コードでない: {municipality_code!r}")
    head = municipality_code[:2] + "000"
    return head + str(check_digit(head))


# ---------------------------------------------------------------------------
# 分離課税の所得からの所得控除（第314条の2第11項、附則第33条の2第7項第3号・第35条の2の2第8項）
# ---------------------------------------------------------------------------

#: 所得控除が総所得金額から引ききれないとき、上場株式等の分離課税の所得のどちらから先に引くかの候補。住民税で区分の間の順序を定めた一次情報がない
#: （docs/public-sources/20261111_impl-research3_juminzei-laws-and-soumu.md §3）。所得税の措通31・32共−4 の順（配当が先）を最初の候補にする。
ORDER_DIVIDEND_FIRST = "上場株式等に係る配当所得等の金額から先に控除"
ORDER_GAIN_FIRST = "上場株式等に係る譲渡所得等の金額から先に控除"


def separate_deductions(remaining: int, dividend: int, gain: int, order: str) -> tuple[int, int]:
    """総所得金額から引ききれない所得控除の額 remaining を、上場株式等に係る配当所得等の金額・譲渡所得等の金額から控除する額（配当の分, 譲渡の分）。"""
    r = max(remaining, 0)
    d, g = max(dividend, 0), max(gain, 0)
    if order == ORDER_DIVIDEND_FIRST:
        x = min(r, d)
        return x, min(r - x, g)
    if order == ORDER_GAIN_FIRST:
        y = min(r, g)
        return min(r - y, d), y
    raise ValueError(f"知らない順序: {order!r}")


def separate_taxable_total(remaining: int, dividend: int, gain: int, order: str, unit: int) -> int:
    """順序 order で控除した後の課税配当所得等と課税譲渡所得等（それぞれ千円未満切捨て）の合計（住民税の率は区分の間で同じなので、税額はこれで決まる）。"""
    x, y = separate_deductions(remaining, dividend, gain, order)
    return floor_unit(dividend - x, unit) + floor_unit(gain - y, unit)


# ---------------------------------------------------------------------------
# 均等割の軽減（第311条）
# ---------------------------------------------------------------------------


def reduced_per_capita(rate: int, first: bool, second: bool, data: Any) -> tuple[int, str | None]:
    """第311条の条例の軽減（注入データ 住民税.均等割の軽減 の中身）を当てた市町村民税の均等割の額と、決まらないときの欄の名前。

    第1号（自身が均等割を納付する義務がある同一生計配偶者・扶養親族）・第2号（第1号の者を2人以上有する）のどちらにも当たらないか、
    条例が軽減を定めていなければ税率のまま。当たる号の額の欄がない、又は両方に当たって額が違えば決まらない（欄の名前を返す）。
    """
    if not (first or second) or not data or not data.get("軽減する"):
        return rate, None
    names = [n for n, hit in (("第1号の均等割の額", first), ("第2号の均等割の額", second)) if hit]
    got = [data.get(n) for n in names]
    if any(v is None for v in got):
        return rate, "・".join(n for n, v in zip(names, got) if v is None)
    if len({int(v) for v in got}) > 1:
        return rate, "第1号と第2号の両方に当たる者の均等割の額（条例の定め）"
    return min(int(got[0]), rate), None


# ---------------------------------------------------------------------------
# 退職所得の分離課税（第328条〜第328条の3、第50条の2〜第50条の4）
# ---------------------------------------------------------------------------


def retirement_separate_tax(retirement_income: int, rates: Any) -> int:
    """分離課税に係る所得割の額（市町村民税＋道府県民税）：退職所得の金額（千円未満切捨て）× 6%・4%、それぞれ百円未満切捨て。"""
    if retirement_income <= 0:
        return 0
    base = floor_unit(retirement_income, int(rates.端数.課税標準の単位))
    unit = int(rates.端数.確定金額の単位)
    r = rates.分離課税.退職所得
    return sum(floor_unit(Fraction(base) * _r(r[e]), unit) for e in ENTITIES)


# ---------------------------------------------------------------------------
# 住民税の雑損失の繰越控除（第313条第9項、施行令第48条の3。2026-11-12、JM-32）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JuminCasualty:
    """住民税の雑損失の繰越控除の額と、控除の後の各所得（総所得金額〔退職所得を除く〕・上場株式等の配当所得等・譲渡所得等・退職所得金額）。"""

    deducted: int
    total: int
    dividend: int
    gain: int
    retirement: int


def jumin_casualty_carryforward(
    merged_total: int, retirement: int, dividend: int, gain_or_loss: int, offset: bool, listed_carry_used: int, net_carried: int, casualty_carried: int
) -> JuminCasualty:
    """前年の所得の計算で、純損失の繰越控除の後の各所得から住民税の雑損失を控除する（第313条第9項）。

    - merged_total は損益通算の後・繰越控除の前の合計（総所得金額＋退職所得金額＋上場株式等の所得：所得税の合計所得金額と同じ組み立て。分離課税に係る
      退職所得のある人は住民税の合計所得金額）、retirement はそのうちの退職所得金額（分離課税の人は0）。
    - 上場株式等：損益通算（offset）と繰越控除（listed_carry_used：所得税の控除した額）は所得税の計算の例（第313条第2項・附則第35条の2の6）。
    - 純損失は総所得金額から、次に退職所得金額から（施行令第48条の3第1項第2号イ・ハ。山林所得は範囲外）。上場分には及ばない。
    - 雑損失は総所得金額、次に上場株式等の配当所得等・譲渡所得等、次に退職所得金額から（施行令第48条の3第1項第2号ホは総所得金額 → 山林 → 退職。
      上場分の位置は所得税の順〔措令4の2⑨・25の11の2⑳〕の読み：basis.JUMIN_CASUALTY_ORDER）。
    計算例：docs/inferences/20261112_impl-research5_juminzei-zasson-cases.md。
    """
    d = max(dividend, 0)
    g = max(gain_or_loss, 0)
    if offset:
        d -= min(d, max(-gain_or_loss, 0))
    t = merged_total - retirement - d - g
    lc = min(max(listed_carry_used, 0), d + g)
    from_g = min(lc, g)
    d -= lc - from_g
    g -= from_g
    n_t = min(net_carried, max(t, 0))
    n_r = min(net_carried - n_t, retirement)
    t -= n_t
    r = retirement - n_r
    c = min(max(casualty_carried, 0), max(t, 0) + d + g + r)
    rest = c
    a = min(rest, max(t, 0))
    rest -= a
    b = min(rest, d)
    rest -= b
    e = min(rest, g)
    rest -= e
    return JuminCasualty(c, t - a, d - b, g - e, r - rest)


__all__ = [
    "ENTITIES",
    "JuminCasualty",
    "jumin_casualty_carryforward",
    "ORDER_DIVIDEND_FIRST",
    "ORDER_GAIN_FIRST",
    "REGIMES",
    "ChainInput",
    "ChainResult",
    "ChainRules",
    "EntityResult",
    "adjustment_base",
    "basic_deduction",
    "casualty_deduction",
    "casualty_fraction_matters",
    "check_digit",
    "compute_chain",
    "dividend_credit",
    "dividend_split",
    "earthquake_exact",
    "exemption_line",
    "filing_special_ratio",
    "floor_unit",
    "levy_fraction",
    "life_insurance_deduction",
    "life_insurance_exact",
    "medical_deduction",
    "medical_fraction_matters",
    "per_capita_with_income_levy",
    "prefecture_code",
    "reduced_per_capita",
    "retirement_separate_tax",
    "round_down_to_step",
    "separate_deductions",
    "separate_taxable_total",
    "special_ratio",
    "special_ratio_with_separate",
    "specified_relative_amount",
    "spouse_deduction",
    "spouse_special_deduction",
]

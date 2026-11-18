"""規則モジュール kokuho の純粋関数（国民健康保険料〔税〕の法令の構造）。OpenFisca を知らない。整数の円と Fraction だけ（float は使わない）。

出典（docs/public-sources/20261109_round2_kokuho-premium-structure.md。以下 [KHP]）：
  - 所得割の算定の基礎（基礎控除後の総所得金額等）：[KHP] §4.1・§4.2（国保令第29条の7第2項第4号・第5号、地法第703条の4第6項・第7項、地法第314条の2第2項）
  - 制度ごとの所得の段階（雑損失の繰越控除をしない・専従者給与を足し戻す）：docs/hypotheses/20261109_round2_kokuho-core-vs-injected.md H11
  - 軽減（7割・5割・2割）の判定の式・給与所得者等・65歳以上の年金の15万円：[KHP] §6.1・§6.2
  - 賦課額の構成（4つの区分）・方式・按分・十八歳以上被保険者均等割：[KHP] §2・§3・§9
  - 賦課限度額：[KHP] §5、未就学児の均等割の減額：[KHP] §7、国保税の確定金額の100円未満の切捨て：[KHP] §10

読みの印（法令の読み。D22 S1）：
  - 賦課限度額は、軽減・未就学児・18歳未満の均等割の減額の **後** の区分ごとの賦課額に当てる（限度額の条は「賦課額は…を超えることが
    できない」、減額の条は「世帯主に対して賦課する被保険者均等割額…を減額する」。減額した均等割額を含む額が賦課額と読む）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

#: 賦課額の区分（injection_points.KUBUN と同じ名前。令和8年度から子ども・子育て支援納付金賦課額が加わる：[KHP] §2.3）。
基礎 = "基礎賦課額"
後期 = "後期高齢者支援金等賦課額"
介護 = "介護納付金賦課額"
子ども = "子ども・子育て支援納付金賦課額"
KUBUN_ALL = (基礎, 後期, 介護, 子ども)

#: 方式（injection_points.HOSHIKI と同じ名前）。
方式_イ = "所得割・資産割・被保険者均等割・世帯別平等割"
方式_ロ = "所得割・被保険者均等割・世帯別平等割"
方式_ハ = "所得割・被保険者均等割"

#: 軽減の区分（政令の判定の段階。実際に減額する割合は市町村が選ぶ：[KHP] §6.1 第3号〜第5号）。
軽減_7割 = "7割"
軽減_5割 = "5割"
軽減_2割 = "2割"
軽減_なし = "なし"
KEIGEN_TIERS = (軽減_7割, 軽減_5割, 軽減_2割, 軽減_なし)

#: 軽減の割合（injection_points の 国保.軽減の割合 の値）→ 段階ごとの割合（十分の）。第4号・第5号の市町村は2割の段階を減額しない。
_KEIGEN_RATIOS: Mapping[str, Mapping[str, Fraction]] = {
    "7割・5割・2割": {軽減_7割: Fraction(7, 10), 軽減_5割: Fraction(5, 10), 軽減_2割: Fraction(2, 10), 軽減_なし: Fraction(0)},
    "6割・4割": {軽減_7割: Fraction(6, 10), 軽減_5割: Fraction(4, 10), 軽減_2割: Fraction(0), 軽減_なし: Fraction(0)},
    "5割・3割": {軽減_7割: Fraction(5, 10), 軽減_5割: Fraction(3, 10), 軽減_2割: Fraction(0), 軽減_なし: Fraction(0)},
}


# ---------------------------------------------------------------------------
# 所得の段階（H11）と所得割の算定の基礎
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResidentIncome:
    """住民税（地方税法）の所得の段階（1人分。H11）。

    - total：地方税法第313条第1項の総所得金額等（純損失・雑損失の繰越控除の後、専従者給与・専従者控除を差し引いた後）。
    - casualty_carryforward：雑損失の繰越控除の額（同条第9項の雑損失の部分）。所得割の基礎では控除しない（足し戻す）。
    - family_employee：青色事業専従者給与・事業専従者控除の額（同条第3項〜第5項）。軽減の判定では差し引かない（足し戻す）。
    - separate：他の所得と区分して計算される所得の金額（分離課税の所得。国保令第29条の7第2項第4号・第6項第1号のかっこ書き）。
      上場株式等に係る譲渡所得等の金額は譲渡損失の繰越控除（地方税法附則第35条の2の6第11項）の後の額（第6項第1号のかっこ書きの明文と、
      附則第35条の2の6第13項の読替え：docs/public-sources/20261112_impl-research4_kokuho-laws.md §2）。
    - pension_income：公的年金等に係る所得の金額（65歳以上の年金の15万円の特例に使う）。
    - pension_65：前年中に65歳以上の者に係る公的年金等控除額の控除を受けたか。
    """

    total: int
    casualty_carryforward: int = 0
    family_employee: int = 0
    separate: int = 0
    pension_income: int = 0
    pension_65: bool = False


def resident_basic_deduction(gokei: int, table: Sequence[tuple[int | None, int]]) -> int:
    """住民税の基礎控除（地法第314条の2第2項）。table は（合計所得金額の上限〔以下〕, 控除額）の昇順。上限 None は最後の段。"""
    for cap, amount in table:
        if cap is None or gokei <= cap:
            return amount
    return 0


def resident_income(total_all: int, retirement: int, separate: int, *, casualty: int = 0, **kw: Any) -> ResidentIncome:
    """住民税の窓口の値から ResidentIncome を作る（2026-11-11：退職所得から控除した繰越控除を分ける）。

    total_all は住民税の総所得金額等（純損失・雑損失の繰越控除の後。退職所得金額〔分離課税でないもの〕と分離課税の所得を含む）、
    retirement は総所得金額等に含まれる退職所得金額（控除の前）、casualty は控除した雑損失の繰越控除の額。
    繰越控除は総所得金額 → 分離課税の所得 → 退職所得金額の順で控除し（所得税法施行令第204条第1項第2号と措置法施行令の読替え：
    docs/public-sources/20261111_impl-research3_joto-junjo-laws-and-nta.md、docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md）、
    雑損失は純損失の後に控除する（同条第2項）。だから退職所得金額から控除した額は max(0, retirement − total_all) で、そのうち雑損失の分は
    min(casualty, その額)。総所得金額と分離課税の所得の合計（繰越控除の後）は max(0, total_all − retirement)。
    返す total は「分離課税の所得を除いた総所得金額（雑損失の控除の後）」で、casualty_carryforward には総所得金額・分離課税の所得から
    控除した雑損失だけを入れる（退職所得から控除した雑損失は国保の所得に入らない退職所得の側の控除なので足し戻さない）。
    """
    on_retirement = max(0, retirement - total_all)
    casualty_on_income = casualty - min(casualty, on_retirement)
    return ResidentIncome(max(0, total_all - retirement) - separate, casualty_carryforward=casualty_on_income, separate=separate, **kw)


def shotokuwari_base(income: ResidentIncome, deduction: int, cut: int = 0) -> int:
    """基礎控除後の総所得金額等（国保令第29条の7第2項第4号・第5号、地法第703条の4第6項・第7項）。

    総所得金額等（雑損失の繰越控除をしない）＋分離課税の所得 − 住民税の基礎控除。0 未満は 0。
    cut は非自発的失業者の特例で総所得金額から減る額（国保令第29条の7の2：unemployment_cut）。
    """
    return max(0, income.total + income.casualty_carryforward + income.separate - cut - deduction)


def keigen_income(income: ResidentIncome, pension_special: int, cut: int = 0) -> int:
    """軽減の判定に使う1人分の所得（国保令第29条の7第6項第1号・第2号、附則第5条。H11）。

    総所得金額等（専従者給与・専従者控除を差し引かない）＋分離課税の所得。65歳以上の公的年金等の控除を受けた人は、
    公的年金等に係る所得から pension_special（15万円）を控除する（控除しきれない額は 0 とし、他の所得から差し引かない：
    「公的年金等に係る所得」をその額に読み替える規定なので、読み替えた所得は 0 を下回らないと読む）。
    cut は非自発的失業者の特例で総所得金額から減る額（減らした総所得金額等は 0 を下回らない）。
    """
    total = income.total + income.family_employee + income.separate
    if cut:
        total = max(0, total - cut)
    if income.pension_65 and income.pension_income > 0:
        total -= min(pension_special, income.pension_income)
    return total


def unemployment_cut(salary: int, gross: int, thirty: int) -> int:
    """非自発的失業者の特例（国保令第29条の7の2・地方税法第703条の5の2：[KHP] §4.3）で総所得金額から減る額。

    salary は所得税法第28条第2項により計算した給与所得の金額、thirty はその100分の30（1円未満の端数は根拠がなく候補で丸めた額）、
    gross は損益通算の後・繰越控除の前の総所得金額（分離課税の所得・退職所得を除く）。給与所得を thirty に置き換えた総所得金額は
    max(0, gross − (salary − thirty))（給与所得は損益通算で損失を受ける側なので、総所得金額が0になるまで減る）。減る額はその差。
    繰越控除の後の値に当てても同じ額になる（繰越控除は控除の前の額を超えて控除しないので、控除の後の額から同じ額を減らして0で止める）。
    """
    return min(max(0, gross), max(0, salary - thirty))


# ---------------------------------------------------------------------------
# 軽減の判定（7割・5割・2割）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeigenRules:
    """軽減の判定の基準（年度ごと。[KHP] §6.1・§6.2）。

    base：地法第314条の2第2項第1号の金額（43万円）、per_earner：給与所得者等が2人以上のときの1人あたりの加算（10万円）、
    per_member_5：5割の1人あたり（a）、per_member_2：2割の1人あたり（b）。
    """

    base: int
    per_earner: int
    per_member_5: int
    per_member_2: int


def keigen_thresholds(k: int, n: int, rules: KeigenRules) -> tuple[int, int, int]:
    """7割・5割・2割の基準額（この額を超えない世帯が該当）。k＝給与所得者等の数、n＝被保険者と特定同一世帯所属者の数。"""
    seven = rules.base + rules.per_earner * max(0, k - 1)
    five = seven + n * rules.per_member_5
    two = seven + n * rules.per_member_2
    return seven, five, two


def keigen_tier(total: int, k: int, n: int, rules: KeigenRules) -> str:
    """軽減の区分（政令の段階）。合算額 total が基準額を「超えない」なら該当。"""
    seven, five, two = keigen_thresholds(k, n, rules)
    if total <= seven:
        return 軽減_7割
    if total <= five:
        return 軽減_5割
    if total <= two:
        return 軽減_2割
    return 軽減_なし


def is_earner(kyuyo_revenue: int, pension_revenue: int, age_65: bool, *, kyuyo_min: int, pension_min_under65: int, pension_min_65: int) -> bool:
    """給与所得者等か（[KHP] §6.1 第1号のかっこ書き）：給与等の収入金額が kyuyo_min（55万円）を超えるか、
    公的年金等の収入金額が 65歳未満は pension_min_under65（60万円）、65歳以上は pension_min_65（110万円。附則第5条で125万円）を超えるか。"""
    if kyuyo_revenue > kyuyo_min:
        return True
    limit = pension_min_65 if age_65 else pension_min_under65
    return pension_revenue > limit


def keigen_ratio(tier: str, scheme: str) -> Fraction:
    """軽減の段階と市町村の割合の組（注入データ 国保.軽減の割合）から、減額の割合。"""
    return _KEIGEN_RATIOS[scheme][tier]


# ---------------------------------------------------------------------------
# 市町村の賦課の定め（注入データを1つにまとめたもの）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KubunRule:
    """区分ごとの方式・率・額・限度額（注入データ 国保.賦課の方式・国保.率と額・国保.賦課限度額）。"""

    method: str
    income_rate: Fraction = Fraction(0)
    asset_rate: Fraction = Fraction(0)
    per_capita: int = 0
    per_household: int = 0
    per_adult: int = 0  # 18歳以上被保険者均等割額（子ども・子育て支援納付金賦課額だけ）
    limit: int | None = None
    per_household_specified: int | None = None  # 特定世帯・特定継続世帯の世帯別平等割額（注入データ 国保.特定世帯の世帯別平等割額）


#: 注入データ 国保.端数処理 の値 → 1円未満の端数の処理。
ROUNDING: Mapping[str, Callable[[Fraction], int]] = {
    "切捨て": lambda x: math.floor(x),
    "四捨五入": lambda x: math.floor(x + Fraction(1, 2)),
    "切上げ": lambda x: math.ceil(x),
}

#: 特定世帯・特定継続世帯（国保令第29条の7第2項第8号ロ・ハ）。
特定世帯 = "特定世帯"
特定継続世帯 = "特定継続世帯"


@dataclass(frozen=True)
class MunicipalRules:
    """世帯の市町村の賦課の定め。levy は "料" か "税"。kubun は区分 → KubunRule。keigen は軽減の割合の組。
    preschool_ratio は未就学児の被保険者均等割の減額の割合（料は政令の十分の五、税は条例の割合〔注入データ〕）。

    2026-11-11 に足した欄（注入データ。なければ従来の年額の計算）：
    - rounding：按分・減額の1円未満の端数の処理（国保.端数処理。ROUNDING の名前）。
    - specified：世帯が特定世帯・特定継続世帯なら その名前（世帯別平等割額を KubunRule.per_household_specified にする。介護の区分を除く）。
    - month_ratio：月割りの1月分の割合（国保.年度の途中の資格の月割り。月割りしないときは 1/12 で月数 12）。
    - birth_ratio：産前産後の減額の1月分の割合（国保.産前産後の減額の算定）。
    """

    levy: str
    kubun: Mapping[str, KubunRule]
    keigen: str
    preschool_ratio: Fraction
    rounding: str | None = None
    specified: str | None = None
    month_ratio: Fraction = Fraction(1, 12)
    birth_ratio: Fraction = Fraction(0)
    household_months: int = 12
    household_kaigo_months: int = 12


def _frac(v: Any) -> Fraction:
    if v is None:
        return Fraction(0)
    return Fraction(int(v["num"]), int(v["den"]))


def _ratio_json(r: Fraction | None) -> Any:
    return None if r is None else {"num": r.numerator, "den": r.denominator}


def rules_to_json(
    levy: str,
    kubun: Mapping[str, Mapping[str, Any]],
    keigen: str,
    preschool_ratio: Fraction | None,
    *,
    rounding: str | None = None,
    specified: str | None = None,
    month_ratio: Fraction | None = None,
    birth_ratio: Fraction | None = None,
    household_months: int = 12,
    household_kaigo_months: int = 12,
) -> str:
    """賦課の定め（入力変数 国保_賦課の定め の文字列）を決定的な JSON にする。率は {num, den}。"""
    data: dict[str, Any] = {
        "賦課": levy,
        "区分": {k: dict(v) for k, v in sorted(kubun.items())},
        "軽減の割合": keigen,
        "未就学児の減額の割合": _ratio_json(preschool_ratio),
    }
    extra = {
        "端数処理": rounding,
        "特定世帯": specified,
        "月割りの1月分の割合": _ratio_json(month_ratio),
        "産前産後の1月分の割合": _ratio_json(birth_ratio),
        "平等割の月数": None if household_months == 12 else household_months,
        "介護の平等割の月数": None if household_kaigo_months == 12 else household_kaigo_months,
    }
    data.update({k: v for k, v in extra.items() if v is not None})
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rules_from_json(text: str) -> MunicipalRules | None:
    """国保_賦課の定め の文字列を読む。空の文字列（データがない・国保の世帯でない）は None。"""
    if not text:
        return None
    data = json.loads(text)
    kubun = {}
    for name, v in data["区分"].items():
        kubun[name] = KubunRule(
            method=v["方式"],
            income_rate=_frac(v.get("所得割率")),
            asset_rate=_frac(v.get("資産割率")),
            per_capita=int(v.get("被保険者均等割額", 0)),
            per_household=int(v.get("世帯別平等割額", 0)),
            per_adult=int(v.get("18歳以上被保険者均等割額", 0)),
            limit=None if v.get("限度額") is None else int(v["限度額"]),
            per_household_specified=None if v.get("特定世帯の世帯別平等割額") is None else int(v["特定世帯の世帯別平等割額"]),
        )
    ratio = data.get("未就学児の減額の割合")
    month = data.get("月割りの1月分の割合")
    return MunicipalRules(
        levy=data["賦課"],
        kubun=kubun,
        keigen=data["軽減の割合"],
        preschool_ratio=_frac(ratio) if ratio is not None else Fraction(0),
        rounding=data.get("端数処理"),
        specified=data.get("特定世帯"),
        month_ratio=_frac(month) if month is not None else Fraction(1, 12),
        birth_ratio=_frac(data.get("産前産後の1月分の割合")),
        household_months=int(data.get("平等割の月数", 12)),
        household_kaigo_months=int(data.get("介護の平等割の月数", 12)),
    )


# ---------------------------------------------------------------------------
# 世帯の保険料（税）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Household:
    """世帯の材料（按分の基礎の合計と人数）。どれも国保の被保険者の分だけ（介護は介護納付金賦課被保険者の分）。

    - base：基礎控除後の総所得金額等の合計、base_kaigo：そのうち介護納付金賦課被保険者の分。
    - asset・asset_kaigo：資産割の基礎の合計。
    - insured：被保険者の数、kaigo：介護納付金賦課被保険者の数、adults：18歳以上被保険者の数、preschool：未就学児の被保険者の数。
    - household・household_kaigo：世帯別平等割を賦課する割合（月割りのときは平等割の月数×1月分の割合。介護の区分は介護納付金賦課被保険者がいる月）。

    2026-11-11：月割り・産前産後の減額があるときは、各欄は人ごとの割合（月割りの月数×1月分の割合 − 産前産後の月数×1月分の割合）で
    重みを付けた合計（Fraction）。所得割・均等割は産前産後の減額の分を差し引いた重み、資産割・未就学児は月割りの重みだけ（減額の対象は
    所得割額・均等割額：国保令第29条の7第6項第8号、[KHP] §8）。月割り・減額がなければ従来どおり人数と合計。
    """

    base: int | Fraction
    base_kaigo: int | Fraction
    asset: int | Fraction
    asset_kaigo: int | Fraction
    insured: int | Fraction
    kaigo: int | Fraction
    adults: int | Fraction
    preschool: int | Fraction
    household: int | Fraction = 1
    household_kaigo: int | Fraction = 1


@dataclass(frozen=True)
class KubunAmount:
    """区分ごとの賦課額（exact は減額の後・限度額の前の額、amount は限度額を当てた額）。"""

    kubun: str
    exact: Fraction
    amount: Fraction
    fractional: bool


@dataclass(frozen=True)
class Premium:
    """世帯の保険料（税）の額。total は区分の合計（税は100円未満を切り捨てた額）。fractional は1円未満の端数が生じたか
    （按分・減額の端数は条例の事項で、法令では決まらない：[KHP] §10。注入データ 国保.端数処理 があればその処理で丸めるので False）。
    base_not_thousand は国保税で、課税標準（基礎控除後の総所得金額等）に千円未満があるか（地法第20条の4の2第1項が及ぶかは
    一次情報で未確認：[KHP] §10）。"""

    total: int
    kubun: tuple[KubunAmount, ...] = field(default_factory=tuple)
    fractional: bool = False
    base_not_thousand: bool = False


def _floor_100(x: Fraction) -> int:
    """地法第20条の4の2第3項：確定金額の100円未満の端数を切り捨てる。"""
    return int(x // 100) * 100


def _rounder(rules: MunicipalRules) -> Callable[[Fraction], Fraction]:
    """按分・減額の1円未満の端数の処理（注入データ 国保.端数処理）。なければ丸めない。"""
    if rules.rounding is None:
        return lambda x: Fraction(x)
    fn = ROUNDING[rules.rounding]
    return lambda x: Fraction(fn(Fraction(x)))


def kubun_amount(name: str, rule: KubunRule, h: Household, tier: str, rules: MunicipalRules) -> KubunAmount:
    """区分ごとの賦課額（[KHP] §3・§6・§7・§9）。

    所得割・資産割は按分の基礎の合計に率を掛ける。被保険者均等割・十八歳以上被保険者均等割・世帯別平等割は軽減の割合で減額し、
    未就学児の均等割は軽減の後の額に割合を掛けて減額し（基礎・後期・子どもの区分。介護の区分は未就学児がいない）、
    子どもの区分の18歳未満被保険者の均等割は前の減額の後の額を全額減額する。限度額は減額の後の額に当てる（モジュールの説明の読み）。
    特定世帯・特定継続世帯は世帯別平等割額を注入データの額にする（介護の区分には特定世帯の定めがない：[PS3-KH] §4）。
    端数処理があれば、所得割額・資産割額・均等割額・十八歳以上被保険者均等割額・平等割額・未就学児の減額の額のそれぞれを丸める（読み）。
    """
    kaigo = name == 介護
    members = h.kaigo if kaigo else h.insured
    if members == 0:
        return KubunAmount(name, Fraction(0), Fraction(0), False)
    rnd = _rounder(rules)
    base = h.base_kaigo if kaigo else h.base
    asset = h.asset_kaigo if kaigo else h.asset
    r = keigen_ratio(tier, rules.keigen)
    raw: list[Fraction] = [rule.income_rate * base]
    if rule.method == 方式_イ:
        raw.append(rule.asset_rate * asset)
    capita = Fraction(rule.per_capita) * (1 - r)  # 1人分の被保険者均等割額（軽減の後）
    if name == 子ども:
        adult_extra = Fraction(rule.per_adult) * (1 - r)
        # 18歳未満の被保険者の子どもの区分の均等割は全額減額（前の減額の後の額。第6項第10号・第11号）。18歳以上の分だけを数える
        raw.append(capita * h.adults)
        raw.append(adult_extra * h.adults)
        preschool_reduction = Fraction(0)  # 未就学児は18歳未満なので、子どもの区分の均等割は全額減額される
    else:
        raw.append(capita * members)
        preschool_reduction = capita * rules.preschool_ratio * (0 if kaigo else h.preschool)
    if rule.method in (方式_イ, 方式_ロ):
        per_household = rule.per_household
        if rules.specified is not None and not kaigo and rule.per_household_specified is not None:
            per_household = rule.per_household_specified
        raw.append(Fraction(per_household) * (1 - r) * Fraction(h.household_kaigo if kaigo else h.household))
    fractional = rules.rounding is None and (any(Fraction(p).denominator != 1 for p in raw) or preschool_reduction.denominator != 1)
    exact = sum((rnd(p) for p in raw), Fraction(0)) - rnd(preschool_reduction)
    amount = exact if rule.limit is None else min(exact, Fraction(rule.limit))
    return KubunAmount(name, exact, amount, fractional)


def household_premium(h: Household, tier: str, rules: MunicipalRules, kubun_names: Sequence[str], bases: Sequence[int] = ()) -> Premium:
    """世帯の保険料（税）の年額。kubun_names はその年度の区分（令和8年度から子ども・子育て支援納付金賦課額）。
    bases は被保険者ごとの基礎控除後の総所得金額等（国保税の課税標準の千円未満の検出に使う）。"""
    amounts = tuple(kubun_amount(k, rules.kubun[k], h, tier, rules) for k in kubun_names)
    exact_total = sum((a.amount for a in amounts), Fraction(0))
    fractional = any(a.fractional for a in amounts)
    if rules.levy == "税":
        total = _floor_100(exact_total)
        not_thousand = any(b % 1000 != 0 for b in bases)
    else:
        total = int(exact_total // 1)
        not_thousand = False
    return Premium(total, amounts, fractional, not_thousand)


def personal_income_levy(
    base: int | Fraction, kaigo: bool, rules: MunicipalRules, kubun_names: Sequence[str], kaigo_base: int | Fraction | None = None
) -> Fraction:
    """1人分の所得割額（区分ごとの所得割の合計。介護の区分は介護納付金賦課被保険者だけ）。端数処理の注入データがなければ丸めない。
    base は月割り・産前産後の重みを付けた額でもよい（kaigo_base は介護の区分の重みの額。省略なら base）。"""
    rnd = _rounder(rules)
    total = Fraction(0)
    for k in kubun_names:
        if k == 介護:
            if not kaigo:
                continue
            total += rnd(rules.kubun[k].income_rate * (base if kaigo_base is None else kaigo_base))
            continue
        total += rnd(rules.kubun[k].income_rate * base)
    return total


__all__ = [
    "Household",
    "KEIGEN_TIERS",
    "KUBUN_ALL",
    "KeigenRules",
    "KubunAmount",
    "KubunRule",
    "MunicipalRules",
    "Premium",
    "ResidentIncome",
    "household_premium",
    "is_earner",
    "keigen_income",
    "keigen_ratio",
    "keigen_thresholds",
    "keigen_tier",
    "kubun_amount",
    "personal_income_levy",
    "resident_basic_deduction",
    "resident_income",
    "rules_from_json",
    "rules_to_json",
    "shotokuwari_base",
    "unemployment_cut",
    "ROUNDING",
    "特定世帯",
    "特定継続世帯",
]

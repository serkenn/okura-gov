"""減価償却の特別な方法（IK-103。2026-11-12）：鉱業用減価償却資産・坑道・鉱業権の生産高比例法（鉱業権は二酸化炭素の貯留事業に関する法律の施行の日の
属する年分以後は生産高等比例法。式は同じ）・旧生産高比例法、国外リース資産の旧国外リース期間定額法、リース資産のリース期間定額法・経過リース期間定額法。

根拠（docs/public-sources/20261112_impl-research5_genka-special-methods.md）：
- 方法と選べる方法：所令120①三・五・六（平成19年3月31日以前の取得）、120の2①三・五・六（以後の取得）、125①（法定償却方法：旧生産高比例法・生産高比例法。
  国外リース資産・リース資産は選べる方法が1つ）。鉱業用の建物・附属設備・構築物（所令6一・二）で平成28年4月1日以後の取得は定額法・生産高比例法だけ
  （120の2①三イ）。坑道は構築物。
- 生産高比例法：取得価額 ÷ 採掘予定数量（耐用年数〔採掘予定年数が短ければその年数〕の期間内の鉱区の採掘予定数量）× その年の採掘数量。
  旧生産高比例法は取得価額から残存価額（別表第十一：有形10%、鉱業権・坑道0）を控除した額を同じく割る（120①三ハ）。
  年の中途で業務の用に供した・供しなくなった年は、その期間の採掘数量で按分する（132①各号ロ）：記録の採掘数量（depreciable_asset の
  extraction_quantities の quantity）はその期間の数量の約束なので、一定単位当たりの金額 × 記録の数量。
- 旧国外リース期間定額法：（取得価額 − 見積残存価額）÷ 賃貸借の期間の月数 × その年の賃貸借の期間の月数（120①六）。
  リース期間定額法：取得価額（契約が令和9年3月31日以前で残価保証額を含むなら、残価保証額を控除した額）÷ リース期間の月数 × その年のリース期間の月数
  （120の2①六。中途で所法60① 以外の事由で移転を受けた資産は移転の日以後の期間）。月数は暦に従い1月未満は1月（120③・120の2③）。
  年の中途の供用の月割（132①）は当てない（132① の括弧書き）。
  経過リース期間定額法（令和7年政令第120号附則7②〜⑥）：令和8年分以後、契約が令和9年3月31日以前で取得価額に残価保証額を含むリース資産に、届出をして
  選べる。最初に当てる年の1月1日の未償却残高 ÷ その日以後のリース期間の月数 × その年の月数。その年の経過リース資産の全部で選ぶ（附則7②ただし書）。
- 累積の限度（所令134）：旧の方法（120①）で有形は取得価額の95%（①一イ）、その後は（取得価額 − 95%相当額 − 1円）÷ 5（②、③で132を準用：年の中途の年は
  採掘数量で按分）、坑道・無形（鉱業権）は取得価額（①一ロ）、国外リース資産は取得価額 − 見積残存価額（①一ニ）。新の方法（120の2）で有形は取得価額 − 1円
  （①二イ）、坑道・無形は取得価額（①二ロ）、リース資産（契約が令和9年3月31日以前）は取得価額 − 残価保証額（①二ハ。経過リース期間定額法の資産は除き、
  イ・ロ：附則7⑥）。
- 少額（所令138）・一括（所令139）はリース資産・国外リース資産を除く（138①・139①の括弧書き）。
- 1円未満は年ごとに切上げ（calc.DEPRECIATION_CEIL：他の方法と同じ国税庁の説明）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ...rounding import ceil_yen
from .common import calendar_months, date_of

#: 方法（選択.減価償却 の depreciation_method の値。リース期間定額法・旧国外リース期間定額法は選ぶ方法でない：選択の語彙にない内部の名前）
M_UOP = "units_of_production"  # 生産高比例法（鉱業権は令和8年政令第93号の施行後は生産高等比例法）
M_OUOP = "old_units_of_production"  # 旧生産高比例法
M_TLEASE = "transitional_lease_term"  # 経過リース期間定額法
M_LEASE = "lease_term"  # リース期間定額法
M_FLEASE = "old_foreign_lease_term"  # 旧国外リース期間定額法
LABELS = {
    M_UOP: "生産高比例法（生産高等比例法）",
    M_OUOP: "旧生産高比例法",
    M_TLEASE: "経過リース期間定額法",
    M_LEASE: "リース期間定額法",
    M_FLEASE: "旧国外リース期間定額法",
}
METHODS = frozenset(LABELS)

MINING = frozenset({"mining_asset", "mine_tunnel", "mining_right"})
#: 残存価額・償却の限度が無形と同じ鉱業用の資産（坑道・鉱業権：別表第十一、所令134①一ロ・二ロ）
ZERO_RESIDUAL = frozenset({"mine_tunnel", "mining_right"})
LEASES = frozenset({"foreign_lease_asset", "lease_asset"})
CLASSES = MINING | LEASES

#: 鉱業用の建物・附属設備・構築物で定率法を選べなくなる取得の日（所令120の2①三イ：平成28年4月1日以後に取得）
MINING_BUILDING_DB_FROM = _dt.date(2016, 4, 1)
#: 残価保証額を控除する契約の締結の日の上限（所令120の2①六・134①二ハ、令和7年政令第120号附則7②：令和9年3月31日以前）
RVG_CONTRACT_UNTIL = _dt.date(2027, 3, 31)
#: 経過リース期間定額法を当てられる最初の年分（令和7年政令第120号附則7②「令和八年以後の各年分」）と、届出のできる最後の年分（同③「令和十年以前の各年分」）
TRANSITIONAL_FIRST_YEAR = 2026
TRANSITIONAL_LAST_YEAR = 2028
#: 所令134② の均等償却の年数（条文の語「五で除して」）
EQUAL_YEARS = 5

MINING_PLANNED_REASON = (
    "入力の不足：鉱業用減価償却資産・坑道・鉱業権の採掘予定数量（判断.減価償却の区分 の planned_extraction_quantity。耐用年数〔鉱区の採掘予定年数が"
    "短ければその年数〕の期間内の鉱区の採掘予定数量）がない、又は0（所令120①三ハ・120の2①三イ(2)・五ロ）"
)
MINING_QUANTITY_REASON = (
    "入力の不足：生産高比例法・旧生産高比例法の資産で、業務の用に供した年からその年分までのいずれかの年分の採掘数量（depreciable_asset の "
    "extraction_quantities）がない"
)
MINING_YEAR_QUANTITY_REASON = (
    "入力の不足：旧生産高比例法の資産で、償却の累積額が取得価額の95%に達した後の年の中途で業務の用に供しなくなった年分に、その年の鉱区の採掘数量の全部"
    "（extraction_quantities の year_quantity）がない（所令134②③・132①二ロ：均等償却の額を採掘数量で按分する）"
)
LEASE_TERM_REASON = (
    "入力の不足・矛盾：リース資産・国外リース資産のリース期間（depreciable_asset の lease_term）がない、又は取得の日がリース期間の外"
    "（所令120①六・120の2①六）"
)
LEASE_CONTRACT_REASON = (
    "入力の不足：令和9年4月1日以後に取得したリース資産で、契約の締結の日（depreciable_asset の lease_contracted_on）がない"
    "（残価保証額を控除するかは契約の締結の日で決まる：所令120の2①六・134①二ハ）"
)
FOREIGN_RESIDUAL_REASON = (
    "入力の不足：国外リース資産の見積残存価額（depreciable_asset の amounts.estimated_residual_value。賃貸借の終了の時に譲渡するとした場合の対価の額）がない"
    "（所令120①六・②）"
)
TRANSITIONAL_MIX_REASON = (
    "入力の矛盾：経過リース期間定額法（令和7年政令第120号附則7②）は、その年に有する経過リース資産の全部について選ぶ方法だが、同じ年分に"
    "リース期間定額法を選んだ経過リース資産がある（附則7②ただし書）"
)


def contract_known_until_cutoff(asset: Mapping[str, Any]) -> bool | None:
    """リース資産の契約が令和9年3月31日以前に締結されたか。締結の日の記録があればそれで、なければ取得の日が上限以前なら真（取得は契約の後）、
    取得の日も上限より後なら None（決まらない）。"""
    a = asset["attributes"]
    if a.get("lease_contracted_on"):
        return date_of(a["lease_contracted_on"]) <= RVG_CONTRACT_UNTIL
    if date_of(asset["when"]["from_on"]) <= RVG_CONTRACT_UNTIL:
        return True
    return None


def transitional_eligible(year: int, asset: Mapping[str, Any]) -> bool:
    """経過リース資産（令和7年政令第120号附則7②）で、その年分に経過リース期間定額法を当てられるか。"""
    return (
        year >= TRANSITIONAL_FIRST_YEAR
        and contract_known_until_cutoff(asset) is True
        and asset["amounts"].get("residual_value_guarantee", 0) > 0
    )


def candidates(cls: str, acquired: _dt.date, has_notice: bool, value: Mapping[str, Any], year: int, asset: Mapping[str, Any], new_from: _dt.date) -> tuple[str, ...]:
    """特別な資産の、採りうる償却の方法（先頭が法定償却方法：所令125①・123⑤）。has_notice は償却の方法の届出の記録があるか。"""
    old = acquired < new_from
    if cls in ("mining_asset", "mine_tunnel"):
        if old:
            return ("old_units_of_production", "old_straight_line", "old_declining_balance") if has_notice else (M_OUOP,)
        bos = True if cls == "mine_tunnel" else value.get("building_or_structure")
        alt = ("straight_line",) if acquired >= MINING_BUILDING_DB_FROM and bos is True else ("straight_line", "declining_balance")
        return (M_UOP, *alt) if has_notice else (M_UOP,)
    if cls == "mining_right":
        if old:
            return (M_OUOP, "old_straight_line") if has_notice else (M_OUOP,)
        return (M_UOP, "straight_line") if has_notice else (M_UOP,)
    if cls == "foreign_lease_asset":
        return (M_FLEASE,)
    if has_notice and transitional_eligible(year, asset):
        return (M_LEASE, M_TLEASE)
    return (M_LEASE,)


@dataclass(frozen=True)
class Special:
    """特別な方法の計算の材料。"""

    cls: str
    method: str
    cost: int
    placed: _dt.date
    disposed: _dt.date | None
    up_to: int
    intangible: bool = False  # リース資産のうち無形（ソフトウエア）のもの（所令134①二ロ）
    #: 年 → 割増・特別償却の額（外部の値。special_dep.py。2026-11-12）。生産高比例法・旧生産高比例法では、その年の償却費の後に累積額へ足す
    #: （未償却残高・累積の限度に効く。上限を超える部分は足さない：呼び出し側が累積額の差で記録の額と比べる）
    special: Mapping[int, int] | None = None


def _quantities(asset: Mapping[str, Any]) -> dict[int, tuple[Fraction, Fraction | None]]:
    out: dict[int, tuple[Fraction, Fraction | None]] = {}
    for e in asset["attributes"].get("extraction_quantities", ()):
        q = Fraction(e["quantity"]["num"], e["quantity"]["den"])
        yq = Fraction(e["year_quantity"]["num"], e["year_quantity"]["den"]) if e.get("year_quantity") else None
        out[int(e["tax_year"])] = (q, yq)
    return out


def production_schedule(
    s: Special, planned: Fraction, quantities: Mapping[int, tuple[Fraction, Fraction | None]], residual_pct: int, limit_pct: int | None
) -> tuple[list[tuple[int, int, int]], str | None]:
    """生産高比例法・旧生産高比例法の年ごとの償却費。(年, 償却費, 累計) の並びと問題（あれば）。

    residual_pct は旧生産高比例法の残存割合（別表第十一。新の方法は0）、limit_pct は旧の方法の有形の累積の限度（所令134①一イ。None は限度が上限の額だけ）。
    """
    cost = s.cost
    zero = s.cls in ZERO_RESIDUAL
    cap = cost if zero else cost - 1  # 134①二イ・ロ、134②（取得価額−1円）、134①一ロ（坑道・無形は取得価額）
    limit95 = ceil_yen(Fraction(cost * limit_pct, 100)) if limit_pct is not None and not zero else None
    base = Fraction(cost) - (Fraction(cost * residual_pct, 100) if not zero else 0)
    accum = 0
    out: list[tuple[int, int, int]] = []
    for yr in range(s.placed.year, s.up_to + 1):
        if s.disposed is not None and s.disposed.year < yr:
            break
        q = quantities.get(yr)
        upper = cap
        if limit95 is not None and accum >= limit95:
            # 所令134②：前年までの累積が95%に達している →（取得価額−95%相当額−1円）÷5。年の中途の年は採掘数量で按分（134③・132①二ロ・三ロ）
            full = Fraction(cost - limit95 - 1, EQUAL_YEARS)
            if s.disposed is not None and s.disposed.year == yr:
                if q is None or q[1] is None or q[1] == 0:
                    return out, MINING_YEAR_QUANTITY_REASON
                full = full * q[0] / q[1]
        else:
            if q is None:
                return out, MINING_QUANTITY_REASON
            if limit95 is not None:
                upper = limit95  # 134①一イ
            full = base * q[0] / planned
        amount = min(ceil_yen(full), max(0, upper - accum))
        accum += amount
        accum += min((s.special or {}).get(yr, 0), max(0, upper - accum))  # 割増・特別償却（累積額に足す。償却費は普通償却費のまま）
        out.append((yr, amount, accum))
    return out, None


def _term(asset: Mapping[str, Any]) -> tuple[_dt.date, _dt.date] | None:
    """償却に使うリース期間（契約のリース期間のうち、所法60① 以外の事由で移転を受けた資産は移転の日〔取得の日〕以後）。"""
    t = asset["attributes"].get("lease_term")
    if not t:
        return None
    start, end = date_of(t["from_on"]), date_of(t["to_on"])
    acquired = date_of(asset["when"]["from_on"])
    if asset["attributes"].get("acquisition_type") not in ("gift", "inheritance"):
        start = max(start, acquired)
    if end < start:
        return None
    return start, end


def _months_in(yr: int, start: _dt.date, end: _dt.date, disposed: _dt.date | None) -> int:
    lo = max(start, _dt.date(yr, 1, 1))
    hi = min(end, _dt.date(yr, 12, 31))
    if disposed is not None:
        hi = min(hi, disposed)
    return calendar_months(lo, hi)


def lease_schedule(s: Special, asset: Mapping[str, Any], first_transitional: int | None) -> tuple[list[tuple[int, int, int]], str | None]:
    """旧国外リース期間定額法・リース期間定額法・経過リース期間定額法の年ごとの償却費。first_transitional は経過リース期間定額法を最初に当てる年分。"""
    term = _term(asset)
    if term is None:
        return [], LEASE_TERM_REASON
    start, end = term
    cost = s.cost
    amts = asset["amounts"]
    if s.cls == "foreign_lease_asset":
        if "estimated_residual_value" not in amts:
            return [], FOREIGN_RESIDUAL_REASON
        base = cost - amts["estimated_residual_value"]
        cap = base  # 134①一ニ
    else:
        before_cutoff = contract_known_until_cutoff(asset)
        if before_cutoff is None:
            return [], LEASE_CONTRACT_REASON
        rvg = amts.get("residual_value_guarantee", 0) if before_cutoff else 0
        base = cost - rvg
        cap = base if before_cutoff else (cost if s.intangible else cost - 1)  # 134①二ハ／二イ・ロ
    total = calendar_months(start, end)
    accum = 0
    out: list[tuple[int, int, int]] = []
    revised: tuple[int, int, _dt.date] | None = None  # 経過リース期間定額法：(改定取得価額, 改定リース期間の月数, 改定リース期間の初日)
    for yr in range(start.year, s.up_to + 1):
        if s.disposed is not None and s.disposed.year < yr:
            break
        if yr > end.year:
            break
        if first_transitional is not None and yr >= first_transitional:
            if revised is None:
                r_start = max(start, _dt.date(first_transitional, 1, 1))
                revised = (cost - accum, calendar_months(r_start, end), r_start)
                cap = cost if s.intangible else cost - 1  # 附則7⑥：134①二の方法に含め、ハの資産に含めない
            book, months_total, r_start = revised
            full = Fraction(book * _months_in(yr, r_start, end, s.disposed), months_total) if months_total else Fraction(0)
        else:
            full = Fraction(base * _months_in(yr, start, end, s.disposed), total) if total else Fraction(0)
        amount = min(ceil_yen(full), max(0, cap - accum))
        accum += amount
        out.append((yr, amount, accum))
    return out, None


def schedule(
    s: Special, asset: Mapping[str, Any], judgment_value: Mapping[str, Any], residual_tangible_pct: int, limit_pct: int, first_transitional: int | None
) -> tuple[list[tuple[int, int, int]], str | None]:
    """特別な方法の年ごとの償却費（全額。事業専用割合を掛ける前）と問題。"""
    if s.method in (M_UOP, M_OUOP):
        p = judgment_value.get("planned_extraction_quantity")
        planned = Fraction(p["num"], p["den"]) if p else Fraction(0)
        if planned <= 0:
            return [], MINING_PLANNED_REASON
        old = s.method == M_OUOP
        return production_schedule(s, planned, _quantities(asset), residual_tangible_pct if old else 0, limit_pct if old else None)
    return lease_schedule(s, asset, first_transitional if s.method == M_TLEASE else None)


__all__ = [
    "CLASSES",
    "FOREIGN_RESIDUAL_REASON",
    "LABELS",
    "LEASES",
    "LEASE_CONTRACT_REASON",
    "LEASE_TERM_REASON",
    "METHODS",
    "MINING",
    "MINING_PLANNED_REASON",
    "MINING_QUANTITY_REASON",
    "MINING_YEAR_QUANTITY_REASON",
    "M_FLEASE",
    "M_LEASE",
    "M_OUOP",
    "M_TLEASE",
    "M_UOP",
    "Special",
    "TRANSITIONAL_FIRST_YEAR",
    "TRANSITIONAL_LAST_YEAR",
    "TRANSITIONAL_MIX_REASON",
    "ZERO_RESIDUAL",
    "candidates",
    "contract_known_until_cutoff",
    "lease_schedule",
    "production_schedule",
    "schedule",
    "transitional_eligible",
]

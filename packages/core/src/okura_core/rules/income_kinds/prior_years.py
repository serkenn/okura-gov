"""規則モジュール income_kinds：前々年分の業務の収入金額（prior_income_fixed。F-D03）と、業務に係る雑所得の現金主義の選択（C-07）。

2026-11-12（語彙の全種類を規則モジュールが使うようにした作業。IK-64・IK-114・IK-115）。原文は
docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md §4.1（所法67②・所令196の2・197③・所基通67−6）・§4.3（所法120⑥・所基通120−4の2）。

- 所法120⑥：その年に業務に係る雑所得を有し、前々年分の業務に係る雑所得の収入金額が1,000万円を超える人は、収支内訳書などの書類を添付する。
  入力 `所得税_前々年分の業務に係る雑所得の収入金額`（prior_income_fixed の income_source miscellaneous_business、tax_year＝その年分−2 の合計）と、
  式 `所得税_業務に係る雑所得の収支内訳書の添付を要するか`。判定は確定申告書を提出する時までに確定しているところ（所基通120−4の2）：
  fixed_on が問いの提出日より後の記録は数えない。その年に業務に係る雑所得の業務があるのに記録がなければ、未確定（決める手段は事実）。
- 所法67②（現金主義）：選択が true なら、業務に係る雑所得の側を後の段（D21 R3）の対象外にする（IK-64）。前々年分の収入金額が300万円を
  超えると分かっている（前年末現在で確定した記録：所基通67−6）か、選択した業務が業務に係る雑所得でないなら、選択の要件を満たさない入力の矛盾（IK-115）。
  選択が false か、未入力なら原則（所法36①・37①：収入すべき金額・債務の確定した費用）で計算する。未入力を候補で評価しない理由：
  所令197③ は適用を受ける旨の確定申告書への記載を要件にし、候補 true は後の段で値がない（候補で評価すると業務を営む人の全部の所得が対象外になる）。
- 事業所得・不動産所得の prior_income_fixed（business・real_estate）：令和7年分・令和8年分の規定で使うものがない（所令195 の青色の現金主義は前々年分の
  「所得の金額」で、収入金額でない。措法25の2② の前々年分の総収入金額は令和9年分以後：jigyo §3）。記録は受け付けて、計算には使わない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from openfisca_core.model_api import YEAR, Variable

from ...country.entities import 人物
from ...money import INT32_MAX
from ...registry import ModuleInputs, YearContext
from ...result import Means
from .common import reason as _reason
from .common import states_of, undetermined

JIGYO = "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md"
K_CASH = "選択.現金主義（業務に係る雑所得）"
V_PRIOR = "所得税_前々年分の業務に係る雑所得の収入金額"
V_ATTACH = "所得税_業務に係る雑所得の収支内訳書の添付を要するか"
MISC_SOURCE = "miscellaneous_business"  # 語彙（okura_ir.vocabulary の prior_income_fixed）の値。2026-11-13：前は "misc_business" で、語彙に合う記録を読めなかった

CASH_BASIS_REASON = "業務に係る雑所得の現金主義（所法67②）の選択がある（現金主義は後の段：D21 R3）"
CASH_INELIGIBLE_REASON = (
    "入力の矛盾：業務に係る雑所得の現金主義（所法67②）の選択があるが、前々年分の業務に係る雑所得の収入金額（prior_income_fixed。前年末現在で確定したもの："
    "所基通67−6）が300万円を超え、所令196の2 の要件を満たさない"
)
CASH_NOT_MISC_REASON = "入力の矛盾：現金主義（所法67②）の選択をした業務が、業務に係る雑所得の業務でない（事業所得・不動産所得の現金主義は所法67①の青色申告者の特例）"
PRIOR_DUPLICATE_REASON = "入力の矛盾：前々年分の業務に係る雑所得の収入金額（prior_income_fixed）に同じ業務の記録が2件以上ある"


def _records(ctx: YearContext, pid: str, until: _dt.date | None) -> list[Mapping[str, Any]]:
    """その人の前々年分の業務に係る雑所得の収入金額の記録（until より後に確定したものを除く）。"""
    out = []
    for r in ctx.records("prior_income_fixed"):
        if r["roles"]["person"] != pid or r["when"]["tax_year"] != ctx.year - 2 or r["attributes"]["income_source"] != MISC_SOURCE:
            continue
        fixed = r["attributes"].get("fixed_on")
        if until is not None and fixed and _dt.date.fromisoformat(fixed) > until:
            continue
        out.append(r)
    return out


def prior_revenue(ctx: YearContext, pid: str, until: _dt.date | None) -> tuple[int | None, tuple[str, ...], bool]:
    """(前々年分の業務に係る雑所得の収入金額の合計〔記録がなければ None〕, 記録の ID, 同じ業務の記録が2件以上か)。"""
    recs = _records(ctx, pid, until)
    if not recs:
        return None, (), False
    keys = [r["attributes"].get("business_id") for r in recs]
    dup = len(keys) != len(set(keys))
    return sum(r["amounts"]["revenue"] for r in recs), tuple(sorted(r["id"] for r in recs)), dup


def write_prior(ctx: YearContext, out: ModuleInputs, pid: str, has_misc: bool) -> None:
    """入力 所得税_前々年分の業務に係る雑所得の収入金額（所法120⑥ の判定の材料。判定の時点は確定申告書の提出の時：所基通120−4の2）。"""
    fd = getattr(ctx, "filing_date", None)
    until = fd.on if fd is not None else None
    total, ids, dup = prior_revenue(ctx, pid, until)
    states = states_of(_records(ctx, pid, until))
    if dup:
        out.exclude(pid, _reason(PRIOR_DUPLICATE_REASON, ids), V_PRIOR)
    elif total is not None and total > INT32_MAX:
        out.exclude(pid, _reason("業務の売上・必要経費の合計が判定コアの整数の範囲を超える", ids), V_PRIOR)
        dup = True
    missing = ()
    if total is None and has_misc:
        missing = (undetermined(
            f"事実:前々年分の業務に係る雑所得の収入金額:{pid}:{ctx.year}", Means.FACT,
            {"person": pid, "tax_year": ctx.year - 2, "入力": "prior_income_fixed（income_source miscellaneous_business。前々年分の業務に係る雑所得の収入金額の確定値）"},
            ("1,000万円以下", "1,000万円超"),
        ),)
    out.set(V_PRIOR, pid, 0 if total is None or dup else total, ids, states, missing=missing)


def cash_basis(
    ctx: YearContext, pid: str, problems: list[tuple[str, tuple[str, ...], tuple[str, ...]]], side_of: Mapping[str, str],
    side_vars: Mapping[str, Sequence[str]], ids: Mapping[str, set[str]],
) -> None:
    """選択.現金主義（業務に係る雑所得）：true なら業務に係る雑所得の側を後の段の対象外（IK-64）、要件を満たさなければ入力の矛盾（IK-115）。"""
    limit = int(ctx.parameters.所得税.業務に係る雑所得の前々年分の収入金額の基準.現金主義の上限)
    for c in ctx.choices(K_CASH):
        if c["subject"]["person"] != pid or c["when"]["tax_year"] != ctx.year:
            continue
        bid = c["subject"]["business_id"]
        side = side_of.get(bid, "misc")
        ids.setdefault(side, set()).add(c["id"])
        if c["value"] is not True:
            continue  # 選ばない：原則（所法36①・37①）
        if side != "misc":
            problems.append((CASH_NOT_MISC_REASON, (c["id"], bid), tuple(side_vars[side])))
            continue
        total, rids, _ = prior_revenue(ctx, pid, _dt.date(ctx.year - 1, 12, 31))
        if total is not None and total > limit:
            problems.append((CASH_INELIGIBLE_REASON, (c["id"], *rids), tuple(side_vars["misc"])))
            continue
        problems.append((CASH_BASIS_REASON, (c["id"], *rids), tuple(side_vars["misc"])))


class 所得税_前々年分の業務に係る雑所得の収入金額(Variable):
    value_type = int
    entity = 人物
    definition_period = YEAR
    label = "前々年分の雑所得を生ずべき業務に係る収入金額（prior_income_fixed の確定値の合計。提出の時までに確定したもの）"
    reference = [f"{JIGYO}#4.3"]


class 所得税_業務に係る雑所得の収支内訳書の添付を要するか(Variable):
    value_type = bool
    entity = 人物
    definition_period = YEAR
    label = "所得税法第120条第6項：その年に業務に係る雑所得を有し、前々年分の業務に係る雑所得の収入金額が1,000万円を超えるか（総収入金額・必要経費の内容を記載した書類の添付）"
    reference = [f"{JIGYO}#4.3"]

    def formula_2025_01_01(人, period, parameters):
        基準 = parameters(period).所得税.業務に係る雑所得の前々年分の収入金額の基準.収支内訳書の添付の基準
        有する = (
            (人("所得税_業務に係る雑所得の総収入金額", period) != 0)
            | (人("所得税_業務に係る雑所得の必要経費", period) != 0)
            | (人("所得税_業務に係る雑所得の減価償却費", period) != 0)
        )
        return np.logical_and(有する, 人("所得税_前々年分の業務に係る雑所得の収入金額", period) > 基準)


VARIABLES: tuple[type, ...] = (所得税_前々年分の業務に係る雑所得の収入金額, 所得税_業務に係る雑所得の収支内訳書の添付を要するか)

__all__ = ["CASH_BASIS_REASON", "K_CASH", "V_PRIOR", "VARIABLES", "cash_basis", "prior_revenue", "write_prior"]

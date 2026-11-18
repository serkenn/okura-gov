"""規則モジュール income_kinds の situation への写し方（中間表現 → 入力変数）、判断・選択の1か所の宣言、対象外の検出。

法令の値（基準額・率）はここに書かない（式とパラメータの側）。ここで当てるのは、記録をどの所得・どの年分に数えるか、
非課税として数えないもの、判断・選択の値の読み方だけ（根拠は basis.py の RULES）。

対象外（その人・年分のその入力変数を対象外にし、依存する値へ伝える。黙って近似しない）の主なもの：
- 公的年金等：共済組合の公務遺族年金（遺族年金の名の中に公務・職務があるもの）、企業年金の障害の給付、その他の年金、
  支給の理由が「その他」（生命保険契約等の年金を除く）、本人の負担の判断がない企業年金・その他の雑所得の年金、公的年金等の源泉徴収票だけがあって支払の記録がない。
- 一時所得：贈与（法人からか個人からかの事実がない）、業務に関して受けるもの、保険の満期（保険料の支払者が受取人でない・保険料の記録がない・保険期間の記録がない・5年以下の保険）、
  支出の記録に額がない・業務の支出、寄附の返礼品があるのに価額の記録がない（返礼品の経済的利益は一時所得：質疑応答事例 02/37）。
- 退職所得：勤務期間の記録が支払者ごとに1つでない・前の退職手当等の勤務期間の記録がない（記録の不足）・中断や前の勤務の注記（語彙がない）・
  5年以下の役員等勤続期間とそれ以外の混在（所令71の2⑬の額の語彙がない）・役員の区分が事実と合わない。
  判断.退職の性質の退職手当等でない支払（所得の種類の未入力）・5年〜19年内の前の退職手当等の範囲は、候補で分かれれば未確定（D21 R6）。
  退職手当等でない支払で給与としたものは、支払の日の年分の 所得税_退職手当等に当たらないとした給与等の収入金額（kyuyo が足す。IK-25：_retire_salary）。
- 事業・業務・不動産：業務の識別子のない支出・ほかの人の業務・生計を一にする家族への対価（所法56）・雇用契約の書面のある売上・
  現金主義（後の段：D21 R3）・資産や家族の使用の按分のうち家族の使用・按分の判断の対象が記録でない・明らかに区分できるかが判断にない・
  減価償却の対象外の形（assets.py）・不動産の共有（持分）・家族の間の賃貸（所法56）・賃料のない礼金等以外の金額の種類 other の一部・組合事業等。
- 消費税：年の途中で免税と課税が変わる年分の税抜経理・修正申告等がある課税期間の税抜経理（consumption.py）。
- 青色申告：承認の手続の記録から承認の年分が決まらない（最初の年分の記載がない・申請の期限の後・相続による承継）。
  青色申告特別控除：電子帳簿の届出がある（第4項第1号は未実装）・申告の計画の欄が足りない。

配当・株式は下の節の docstring。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from fractions import Fraction
from typing import Any

from ...basis import BasisEntry, BasisType, ReadingFlag, SourceKind
from ...candidates import Candidate
from ...money import INT32_MAX
from ...registry import DecisionSlot, DecisionSpec, ModuleInputs, YearContext, overlaps_year, unique_splits
from ...result import Means, OutOfScopeReason, Split, State
from . import rental_special as rsp
from .assets import (
    K_DEP_CHOICE,
    K_DEP_CLASS,
    ROUNDING_EXPENSE,
    AssetResult,
    CostInfo,
    asset_year,
    dep_class,
    dep_slots,
    disposed_on,
)
from .calc import (
    BLUE_APPROVED,
    BLUE_NOT_APPROVED,
    FILING_ETAX,
    FILING_OTHER,
    FILING_EBOOKS,
    FILING_PAPER,
    RETIRE_GENERAL,
    RETIRE_OFFICER,
    RETIRE_SHORT,
    deduction_by_years,
    retirement_rules,
)
from .common import (
    Interval,
    intersect,
    measure,
    normalize,
    subtract,
    sum_ymd,
    undetermined,
    ymd,
    years_ceil,
    years_floor,
    Indexed as _Indexed,
    add_months as _add_months,
    calendar_months,
    check_amount as _check_amount,
    date_of as _date,
    reason as _reason,
    states_of as _states,
    year_of as _year_of,
)
from .consumption import K_CT, CtPlan, ct_slots, plan as ct_plan, tax_expense, tax_expense_by_business
from .breakdown import REV_HOUSEHOLD, RENT_FLOW_KEYS, REV_SALES, Breakdown, write_breakdown, write_cost_of_sales, write_employers
from . import inventory as inv
from . import prior_years as _prior  # 前々年分の収入金額・現金主義の選択（IK-64・IK-114・IK-115）
from . import rental_choices as _rc  # 不動産所得の区分の材料・計上の方法（IK-116〜IK-119）
from .family import (
    K_REASONABLE,
    K_SEIKEI,
    age_on,
    engagement_months,
    is_relative,
    is_spouse,
    pair_key,
    seikei_slots,
    within_notice,
)

# 入力変数
V_PENSION = "所得税_公的年金等の収入金額"
V_OTHER_MISC_REV = "所得税_その他の雑所得の総収入金額"
V_OTHER_MISC_EXP = "所得税_その他の雑所得の必要経費"
V_PENSION_WITHHOLD = "所得税_公的年金等の源泉徴収税額"
V_RET_WITHHOLD = "所得税_退職所得の源泉徴収税額"
V_WF_TOTAL = "所得税_一時所得の総収入金額"
V_WF_EXP = "所得税_一時所得の支出した金額"
V_RET_INCOME = "所得税_退職手当等の収入金額"
V_RET_YEARS = "所得税_退職所得の勤続年数"
V_RET_KIND = "所得税_退職手当等の区分"
V_RET_DISABLED = "所得税_障害者になったことに直接基因する退職か"
V_RET_PRIOR_YEARS = "所得税_前の退職手当等との重複年数"
V_RET_SHORT_INCOME = "所得税_短期退職手当等の収入金額"
V_RET_OFFICER_INCOME = "所得税_特定役員退職手当等の収入金額"
V_RET_SHORT_DED = "所得税_短期退職所得控除額"
V_RET_OFFICER_DED = "所得税_特定役員退職所得控除額"
V_BIZ_REV = "所得税_事業所得の総収入金額"
V_BIZ_EXP = "所得税_事業所得の必要経費"
V_MISC_REV = "所得税_業務に係る雑所得の総収入金額"
V_MISC_EXP = "所得税_業務に係る雑所得の必要経費"
V_BIZ_DEP = "所得税_事業所得の減価償却費"
V_MISC_DEP = "所得税_業務に係る雑所得の減価償却費"
V_RENT_REV = "所得税_不動産所得の総収入金額"
V_RENT_EXP = "所得税_不動産所得の必要経費"
V_RENT_DEP = "所得税_不動産所得の減価償却費"
V_RENT_SCALE = "所得税_不動産の貸付けが事業として行われているか"
V_RENT_LAND_INT = "所得税_土地等を取得するために要した負債の利子の額"
V_RENT_ALL_VILLA = "所得税_不動産所得の貸付けがすべて別荘等か"
V_BIZ_SALARY = "所得税_事業所得の青色事業専従者給与の額"
V_RENT_SALARY = "所得税_不動産所得の青色事業専従者給与の額"
V_BIZ_FAM_DED = "所得税_事業所得の事業専従者控除額"
V_RENT_FAM_DED = "所得税_不動産所得の事業専従者控除額"
V_FAM_DEEMED = "所得税_事業専従者としてみなされる給与の収入金額"
V_RENT_VILLA_LOSS = "所得税_別荘等の貸付けに係る損失の額"
V_RENT_SPECIAL = "所得税_組合事業等と国外中古建物の不動産所得の損失のうち生じなかったものとみなす金額"
V_FAMILY_SALARY_OUT = "所得税_生計を一にする親族の事業から受けた給与のうち収入金額に含めない額"
V_HOME = "所得税_家内労働者等か"
V_BLUE = "所得税_青色申告の承認の状態"
V_BOOK = "所得税_正規の簿記の要件"
V_FILING = "所得税_青色申告特別控除の申告の要件"
V_ROUNDING = "所得税_所得の金額の端数の候補"
V_DIV_AGG = "所得税_総合課税の配当等の収入金額"
V_DIV_SEP = "所得税_申告分離課税の配当等の収入金額"
V_DIV_AGG_INT = "所得税_総合課税の配当等の負債の利子"
V_DIV_SEP_INT = "所得税_申告分離課税の配当等の負債の利子"
V_DIV_WITHHOLD = "所得税_配当等の源泉徴収税額"
V_SALE_REV = "所得税_上場株式等の譲渡の収入金額"
V_CREDIT_SURPLUS = "所得税_配当控除の対象の剰余金の配当等に係る配当所得の金額"
V_CREDIT_TRUST = "所得税_配当控除の対象の証券投資信託の収益の分配に係る配当所得の金額"
V_CREDIT_FX_TRUST = "所得税_配当控除の対象の一般外貨建等証券投資信託の収益の分配に係る配当所得の金額"
V_SALE_COST = "所得税_上場株式等の譲渡の取得費等"
V_SALE_WITHHOLD = "所得税_上場株式等の譲渡の源泉徴収税額"
# 申告書の欄の材料（2026-11-12 の4回目。forms_items.py。IK-111）
V_SMALL_UNLISTED = "所得税_確定申告不要制度を選択した非上場株式の少額配当等の額"
V_DIV_LOCAL = "所得税_申告する配当等の配当割額"
V_SALE_LOCAL = "所得税_申告する上場株式等の譲渡の株式等譲渡所得割額"
V_MISC_WITHHOLD = "所得税_業務に係る雑所得の源泉徴収税額"

# 判断・選択の種類
K_JIGYO = "判断.事業と称するに至る程度"
K_HOME = "判断.家内労働者等"
K_RELATED = "判断.業務関連性"
K_SHARE = "判断.按分の割合"
K_BOOK = "判断.正規の簿記の宣言"
K_PLAN = "計画.申告の方法と時期"
K_RETIRE = "判断.退職の性質"
K_STOCK = "選択.株式等の申告"
K_PENSION_NATURE = "判断.年金の性質"
K_RENT_SCALE = "判断.不動産の事業的規模"
K_PARTNER = "判断.組合の重要業務の執行"
K_LARGE_HOLDER = "判断.大口株主等"
K_EMPLOY = "判断.雇用か請負か"
EMPLOYMENT_RECEIPT_REASON = (
    "判断.雇用か請負か で雇用とした受取が業務の売上（business_receipt）として記録されている（給与所得なので給与の支払 salary_payment として記録する。kyuyo の入力）"
)


# ---------------------------------------------------------------------------
# 公的年金等・年金の種類ごとの雑所得
# ---------------------------------------------------------------------------

#: 公的年金等として数える (制度, 支給の理由)（所法35③、所令82の2）。
PENSION_PUBLIC: frozenset[tuple[str, str]] = frozenset(
    {("national_pension", "old_age"), ("employees_pension", "old_age"), ("mutual_aid_pension", "old_age")}
)
#: 非課税として数えない (制度, 支給の理由)（公課の禁止・所法9①三ロ・TA1605）。
PENSION_EXEMPT: frozenset[tuple[str, str]] = frozenset(
    {
        ("national_pension", "disability"),
        ("national_pension", "survivor"),
        ("employees_pension", "disability"),
        ("employees_pension", "survivor"),
        ("mutual_aid_pension", "disability"),
        ("mutual_aid_pension", "survivor"),
        ("corporate_pension", "survivor"),
    }
)
PENSION_SLIP_REASON = "公的年金等の源泉徴収票（withholding_slip）があるのに、その年分の課税される年金の支払の記録がない"
PENSION_NATURE_CANDIDATES = (
    Candidate({"public_scheme": True}, "外国の社会保険・共済の制度に基づく年金（公的年金等）"),
    Candidate({"public_scheme": False}, "公的年金等でない（その他の雑所得）"),
)


def _pension_nature_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.年金の性質（支払ごと）：外国の年金が公的な制度か（未入力なら両方。D21 R6）。

    企業年金・生命保険契約等の年金の本人の負担は額なので候補にならない（入力がなければ対象外）。
    """
    out = []
    for rec in ctx.records("pension_payment"):
        if _year_of(rec, "statutory_payment_on") != ctx.year or rec["attributes"]["scheme"] != "foreign_pension":
            continue
        rid = rec["id"]
        out.append(
            DecisionSlot(
                key=rid,
                target={"payment_id": rid},
                matches=lambda j, rid=rid: j["subject"]["payment_id"] == rid,
                candidates=PENSION_NATURE_CANDIDATES,
                persons=(rec["roles"]["recipient"],),
            )
        )
    return out


def _pension(ctx: YearContext, out: ModuleInputs) -> None:
    natures = {j["subject"]["payment_id"]: j for j in ctx.judgments(K_PENSION_NATURE)}
    pays: dict[str, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("pension_payment"):
        if _year_of(rec, "statutory_payment_on") == ctx.year:
            pays.setdefault(rec["roles"]["recipient"], []).append(rec)
    slips: dict[str, list[Mapping[str, Any]]] = {}
    for r in ctx.records("withholding_slip"):
        if r["attributes"]["slip_type"] == "public_pension" and r["when"]["tax_year"] == ctx.year:
            slips.setdefault(r["roles"]["recipient"], []).append(r)
    for pid in ctx.persons:
        recs = sorted(pays.get(pid, []), key=lambda r: r["id"])
        public = other_rev = other_exp = 0
        bad: list[tuple[str, tuple[str, ...]]] = []
        ids: list[str] = [r["id"] for r in recs]
        st = _states(recs)
        public_recs: list[Mapping[str, Any]] = []
        miss: list[Split] = []
        for r in recs:
            scheme = r["attributes"]["scheme"]
            why = r["attributes"]["benefit_reason"]
            name = r["attributes"].get("benefit_name", "")
            rid = r["id"]
            if (scheme, why) in PENSION_PUBLIC:
                public += r["amounts"]["gross"]
                public_recs.append(r)
            elif (scheme, why) in PENSION_EXEMPT:
                if scheme == "mutual_aid_pension" and why == "survivor" and any(w in name for w in ("公務", "職務")):
                    # 共済法の公課の禁止の対象外（国共済法49 ただし書など）だが、所法9①三ロでは遺族の年金は非課税と読める。名指しした
                    # 一次情報がない（nenkin §10-3）→ 非課税・公的年金等の両方で評価し、額が分かれるので未確定（D22 S1）
                    public += r["amounts"]["gross"]
                    public_recs.append(r)
                    miss.append(undetermined(
                        f"一次情報:共済の公務遺族年金:{rid}", Means.PRIMARY_SOURCE,
                        {"person": pid, "payment_id": rid, "事項": "共済組合の公務遺族年金（年金払い退職給付）が所法9①三ロの非課税に当たるか",
                         "決める手段": "国税庁の見解（docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md §10-3）"},
                        ("非課税", "公的年金等の収入金額"),
                    ))
            elif scheme == "corporate_pension" and why == "old_age":
                j = natures.get(rid)
                portion = None if j is None else j["value"].get("employee_contribution_portion")
                if portion is None:
                    bad.append(("企業年金の加入者の負担した金額（判断.年金の性質の employee_contribution_portion）が入力されていない（所法35③三の収入金額の計算）", (rid,)))
                    continue
                public += max(0, r["amounts"]["gross"] - portion)
                public_recs.append(r)
                ids.append(j["id"])
                st |= _states([j])
            elif scheme == "foreign_pension" and why in ("old_age", "other"):
                d = ctx.decision(K_PENSION_NATURE, rid)
                ids += list(d.record_ids)
                st |= set(d.states)
                value = d.value if isinstance(d.value, Mapping) else {}
                if value.get("public_scheme"):
                    public += r["amounts"]["gross"]
                    public_recs.append(r)
                else:
                    portion = value.get("employee_contribution_portion")
                    if portion is None:
                        bad.append(("外国の年金で公的な制度でないものの必要経費（判断.年金の性質の employee_contribution_portion）が入力されていない", (rid,)))
                        continue
                    other_rev += r["amounts"]["gross"]
                    other_exp += portion
            elif scheme == "private_annuity" and why in ("old_age", "other"):
                j = natures.get(rid)
                portion = None if j is None else j["value"].get("employee_contribution_portion")
                if portion is None:
                    bad.append(("生命保険契約等に基づく年金の必要経費（判断.年金の性質の employee_contribution_portion：保険料の総額のうち対応する部分）が入力されていない（所令183）", (rid,)))
                    continue
                other_rev += r["amounts"]["gross"]
                other_exp += portion
                ids.append(j["id"])
                st |= _states([j])
            else:
                # その他の制度・支給の理由が「その他」・企業年金の障害の給付：非課税か、公的年金等か、その他の雑所得かを決める一次情報（企業年金の
                # 障害給付）・事実（制度・理由が「その他」）がない。候補の全部（非課税・公的年金等・その他の雑所得）で額が分かれるので未確定（D21 R6・D22 S1）
                public += r["amounts"]["gross"]
                public_recs.append(r)
                known = scheme == "corporate_pension" and why == "disability"
                miss.append(undetermined(
                    f"{'一次情報' if known else '事実'}:年金の所得の区分:{rid}", Means.PRIMARY_SOURCE if known else Means.FACT,
                    {"person": pid, "payment_id": rid, "scheme": scheme, "benefit_reason": why,
                     ("事項" if known else "入力"): "確定給付企業年金等の障害の給付が非課税か（所法9①三・TA1605 は遺族の給付だけを書く）" if known
                     else "年金の制度（scheme）・支給の理由（benefit_reason）を「その他」でなく具体的に（非課税・公的年金等・その他の雑所得の区分の材料）"},
                    ("非課税", "公的年金等の収入金額", "その他の雑所得"),
                ))
        my_slips = sorted(slips.get(pid, []), key=lambda r: r["id"])
        _check_amount(public, "公的年金等の収入金額")
        excluded = False
        for text, rids in bad:
            for v in (V_PENSION, V_OTHER_MISC_REV, V_OTHER_MISC_EXP):
                out.exclude(pid, _reason(text, rids), v)
            excluded = True
        if my_slips and not public_recs and not bad:
            out.exclude(pid, _reason(PENSION_SLIP_REASON, (s["id"] for s in my_slips)), V_PENSION)
            excluded = True
        if max(public, other_rev) > INT32_MAX and not excluded:
            for v in (V_PENSION, V_OTHER_MISC_REV):
                out.exclude(pid, _reason("年金の収入金額が判定コアの整数の範囲を超える", ids), v)
            excluded = True
        out.set(V_PENSION, pid, 0 if excluded else public, ids, st, missing=miss)
        out.set(V_OTHER_MISC_REV, pid, 0 if excluded else other_rev, ids, st, missing=miss)
        out.set(V_OTHER_MISC_EXP, pid, 0 if excluded else other_exp, ids, st, missing=miss)
        _withhold_from_records(out, ctx, pid, V_PENSION_WITHHOLD, public_recs, my_slips, "公的年金等の支払", excluded)


def _withhold_from_records(
    out: ModuleInputs,
    ctx: YearContext,
    pid: str,
    variable: str,
    pays: list[Mapping[str, Any]],
    slips: list[Mapping[str, Any]],
    what: str,
    excluded: bool,
) -> None:
    """源泉徴収税額：源泉徴収票の値を優先する（D23 K4）。票がなければ支払の記録の額の合計。額が書かれていない支払があれば対象外（0 か未記録かを区別できない）。"""
    if slips:
        amts = [s["amounts"].get("withholding_tax") for s in slips]
        ids = [s["id"] for s in slips]
        missing = [s["id"] for s, a in zip(slips, amts) if a is None]
        if missing or excluded:
            if missing:
                out.exclude(pid, _reason(f"{what}の源泉徴収票に源泉徴収税額の記載がない", missing), variable)
            out.set(variable, pid, 0, ids, _states(slips))
            return
        out.set(variable, pid, sum(a for a in amts if a is not None), ids, _states(slips))
        return
    missing = [r["id"] for r in pays if "withholding_tax" not in r["amounts"]]
    if missing and not excluded:
        out.exclude(pid, _reason(f"{what}に源泉徴収税額（amounts.withholding_tax）が書かれていない。0 か未記録かを区別できない", missing), variable)
    total = 0 if excluded or missing else sum(r["amounts"].get("withholding_tax", 0) for r in pays)
    out.set(variable, pid, total, [r["id"] for r in pays], _states(pays))


# ---------------------------------------------------------------------------
# 一時所得
# ---------------------------------------------------------------------------

WINDFALL_BUSINESS_REASON = (
    "業務との関係が記録にない・業務に関して受ける懸賞の賞金品等がある（所基通34−1：事業所得・雑所得になりうる）"
)
WINDFALL_EXPENSE_REASON = "一時所得の収入を得るために支出した金額の記録に額がない、又は業務の支出（business_expense の業務の識別子つき）を指している"
WINDFALL_INSURANCE_REASON = (
    "保険の満期金等がある。保険料を受取人自身が負担していること（支出の記録の支払者）と、5年を超える保険期間の保険（5年以下の一時払い等は源泉分離課税：TA No.1490）であることが記録から確かめられない"
)
WINDFALL_GIFT_REASON = (
    "寄附の返礼品がある（return_gift）が、その価額（amounts.return_gift_value）の記録がない（返礼品の経済的利益は一時所得：質疑応答事例 02/37）"
)


def _insurance_ok(ctx: YearContext, pid: str, r: Mapping[str, Any], expenses: list[Mapping[str, Any]]) -> bool:
    """保険の満期金等を一時所得に数えられるか：保険料の支出の支払者が全部受取人で、受取の日に終わる保険期間5年超の契約が記録にあるか。"""
    if not expenses or any(e["roles"].get("payer") != pid for e in expenses):
        return False
    on = _date(r["when"]["on"])
    for c in ctx.records("insurance_contract"):
        if c["roles"]["policyholder"] != pid or "to_on" not in c["when"]:
            continue
        start, end = _date(c["when"]["from_on"]), _date(c["when"]["to_on"])
        if end <= on <= _add_months(end, 12) and (end - start).days > 365 * 5:
            return True
    return False


JIGYO_DOC = "docs/public-sources/20261109_impl-prep_jigyo-laws-and-nta.md"
NENKIN_DOC = "docs/public-sources/20261109_round2b_nenkin-laws-and-guidance.md"
A3_DOC = "docs/public-sources/20261112_impl-a3_taishoku-haito-kyufu.md"
GIFT_INDIVIDUAL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="個人からの贈与（windfall_receipt の donor_type: individual）は一時所得の総収入金額に数えない（贈与税の対象。所基通34−1(5) は法人からの贈与）",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達34−1(5)",
    references=(f"{JIGYO_DOC}#6",),
    flags=(ReadingFlag.LEGAL_READING,),
)
UNPAID_PENSION_RULE = BasisEntry(
    type=BasisType.RULE,
    name="未支給年金は遺族の一時所得の収入金額（法律で非課税とされるものを除く）",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="タックスアンサー No.1605（根拠法令等に所法34、所基通34−2）",
    references=(f"{NENKIN_DOC}#4.3", f"{A3_DOC}#5"),
)
RETIRE_AS_WINDFALL_RULE = BasisEntry(
    type=BasisType.RULE,
    name="判断.退職の性質 で退職手当等に当たらず一時所得の収入に当たるとした支払は、一時所得の総収入金額に数える（所法34）",
    source_kind=SourceKind.LAW,
    law="所得税法第34条・第30条第1項",
    references=(f"{JIGYO_DOC}#6",),
)
#: 判断.退職の性質 で退職手当等に当たらず給与とした支払の額（kyuyo が段 事業専従者のみなし給与 で読んで給与等の収入金額に足す。IK-25、2026-11-12）。
V_RETIRE_SALARY = "所得税_退職手当等に当たらないとした給与等の収入金額"
RETIRE_AS_SALARY_RULE = BasisEntry(
    type=BasisType.RULE,
    name="判断.退職の性質 で退職手当等に当たらず給与とした支払は、退職所得に数えず、支払の日の年分の給与等の収入金額に数える",
    source_kind=SourceKind.CIRCULAR,
    law=(
        "所得税法第28条第1項・第30条第1項、所得税基本通達30−1（引き続き勤務する者に支払われる賞与等と同性質のものは退職手当等に当たらない）・"
        "36−9(1)（給与の収入すべき時期：支給日、定めがなければ支給を受けた日）。retirement_payment に支給日の定めを書く欄がないので、"
        "支払の日（when.on）を支給を受けた日として年分を決める（法令の読み。退職の日〔36−10〕では決めない）"
    ),
    references=("docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md#1.2", "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#2.1"),
    flags=(ReadingFlag.LEGAL_READING,),
)


def _unpaid_pensions(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """その年分に受けた未支給年金（benefit_receipt の unpaid_pension_of_deceased。受けた日〔on か区間の始め〕の年）。"""
    out = []
    for r in ctx.records("benefit_receipt"):
        if r["roles"]["recipient"] != pid or r["attributes"]["benefit_type"] != "unpaid_pension_of_deceased":
            continue
        on = r["when"].get("on") or r["when"]["from_on"]
        if _date(on).year == ctx.year:
            out.append(r)
    return sorted(out, key=lambda r: r["id"])


def _retire_as_windfall(ctx: YearContext, pid: str) -> tuple[list[Mapping[str, Any]], Any]:
    """判断.退職の性質 で退職手当等に当たらず一時所得とした、その年分の支払（IK-25）と判断。"""
    pays = _retirement_payments(ctx, pid)
    if not pays:
        return [], None
    d = ctx.decision(K_RETIRE, pid)
    v = d.value if isinstance(d.value, Mapping) else {}
    if v.get("is_retirement_allowance") is False and v.get("income_type") == "occasional":
        return pays, d
    return [], d


def _windfall(ctx: YearContext, out: ModuleInputs) -> None:
    facts = {r["id"]: r for r in ctx.ir["facts"]}
    recs: dict[str, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("windfall_receipt"):
        if _year_of(rec) == ctx.year:
            recs.setdefault(rec["roles"]["recipient"], []).append(rec)
    gifts: dict[str, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("donation"):
        if _year_of(rec) == ctx.year and ("return_gift_value" in rec["amounts"] or rec["attributes"].get("return_gift")):
            gifts.setdefault(rec["roles"]["donor"], []).append(rec)
    for pid in ctx.persons:
        mine = sorted(recs.get(pid, []), key=lambda r: r["id"])
        problems: list[tuple[str, tuple[str, ...]]] = []
        total = 0
        expense = 0
        ids: list[str] = []
        my_gifts = sorted(gifts.get(pid, []), key=lambda r: r["id"])
        for r in my_gifts:  # 寄附の返礼品の経済的利益（価額の記録があるもの）は一時所得の総収入金額に数える
            total += r["amounts"].get("return_gift_value", 0)
            ids.append(r["id"])
        no_value = [r["id"] for r in my_gifts if "return_gift_value" not in r["amounts"]]
        bad_exp: list[str] = []
        exp_recs: list[Mapping[str, Any]] = []
        miss: list[Split] = []
        basis: list[BasisEntry] = []
        gift_basis = False
        unpaid = _unpaid_pensions(ctx, pid)
        for r in unpaid:  # 未支給年金（TA1605）：老齢は一時所得。障害・遺族は法律で非課税とされるものかの一次情報がない（候補で評価）
            reason_ = r["attributes"].get("unpaid_pension_reason")
            if reason_ != "old_age":
                miss.append(undetermined(
                    f"{'一次情報' if reason_ else '事実'}:未支給年金の非課税:{r['id']}", Means.PRIMARY_SOURCE if reason_ else Means.FACT,
                    {"person": pid, "record_id": r["id"], "入力": "未支給年金の元の年金の支給の事由（unpaid_pension_reason）"
                     if reason_ is None else "障害・遺族の年金の未支給分が法律で非課税とされるもの（TA1605 の括弧書き）に当たるか（docs に一次情報がない）"},
                    ("一時所得", "非課税"),
                ))
            total += r["amounts"]["amount"]
            ids.append(r["id"])
        if unpaid:
            basis.append(UNPAID_PENSION_RULE)
        as_wf, rd = _retire_as_windfall(ctx, pid)
        for r in as_wf:  # 退職手当等に当たらず一時所得とした支払（IK-25）。本人の掛金は支出した金額に数える（所基通30−3 と同じ掛金を一時所得の側で読む）
            total += r["amounts"]["gross"]
            expense += r["amounts"].get("employee_contributions", 0)
            ids.append(r["id"])
        if as_wf:
            ids += list(rd.record_ids)
            basis.append(RETIRE_AS_WINDFALL_RULE)
        for r in mine:
            why = r["attributes"]["reason"]
            if r["attributes"].get("business_related") is not False:
                problems.append((WINDFALL_BUSINESS_REASON, (r["id"],)))
            elif why == "gift":
                # 法人からの贈与は一時所得（所基通34−1(5)）、個人からの贈与は贈与税（範囲外で所得税の所得にならない）。
                # donor_type（2026-11-12）で決める。個人からの贈与は一時所得に数えない。未入力なら両方で評価し、額が分かれるので未確定（D21 R6）
                donor = r["attributes"].get("donor_type")
                if donor == "individual":
                    gift_basis = True
                    continue
                if donor is None:
                    miss.append(undetermined(
                        f"事実:贈与者が法人か:{r['id']}", Means.FACT,
                        {"person": pid, "record_id": r["id"], "入力": "贈与者が法人か個人か（windfall_receipt の attributes.donor_type）"},
                        ("法人（一時所得）", "個人（贈与税・所得税の所得でない）"),
                    ))
            mine_exp = []
            for eid in r["attributes"].get("direct_expense_ids", []):
                e = facts[eid]
                amt = e.get("amounts", {}).get("amount")
                if type(amt) is not int or (e["kind"] == "business_expense" and "business_id" in e.get("attributes", {})):
                    bad_exp.append(eid)
                    continue
                expense += amt
                ids.append(eid)
                exp_recs.append(e)
                mine_exp.append(e)
            if why == "insurance_maturity" and not _insurance_ok(ctx, pid, r, mine_exp):
                problems.append((WINDFALL_INSURANCE_REASON, (r["id"],)))
            total += r["amounts"]["amount"]
            ids.append(r["id"])
        excluded = False
        for text, rids in problems:
            for v in (V_WF_TOTAL, V_WF_EXP):
                out.exclude(pid, _reason(text, rids), v)
            excluded = True
        if no_value:
            out.exclude(pid, _reason(WINDFALL_GIFT_REASON, no_value), V_WF_TOTAL)
            excluded = True
        if bad_exp:
            out.exclude(pid, _reason(WINDFALL_EXPENSE_REASON, bad_exp), V_WF_EXP)
            excluded = True
        if (total > INT32_MAX or expense > INT32_MAX) and not excluded:
            for v in (V_WF_TOTAL, V_WF_EXP):
                out.exclude(pid, _reason("一時所得の金額が判定コアの整数の範囲を超える", ids), v)
            excluded = True
        st = _states(mine) | _states(exp_recs) | _states(my_gifts) | _states(unpaid) | _states(as_wf) | (set(rd.states) if as_wf else set())
        if gift_basis:
            basis.append(GIFT_INDIVIDUAL_RULE)
        extra = [r["id"] for r in [*unpaid, *as_wf]] + (list(rd.record_ids) if as_wf else [])
        out.set(V_WF_TOTAL, pid, 0 if excluded else total, [r["id"] for r in [*mine, *my_gifts]] + extra, st, basis=basis, missing=miss)
        out.set(V_WF_EXP, pid, 0 if excluded else expense, ids, st, missing=miss)


# ---------------------------------------------------------------------------
# 退職所得
# ---------------------------------------------------------------------------

#: 所法30④「短期勤続年数（…五年以下）」・⑤「役員等勤続年数が五年以下」。build_inputs からパラメータを引けないので定数で持ち、
#: パラメータ（所得税.退職所得.短期退職手当等.勤続年数の上限・特定役員退職手当等.役員等勤続年数の上限）と同じ値であることをテストで確かめる。
SHORT_SERVICE_LIMIT = 5
OFFICER_SERVICE_LIMIT = 5
RETIREMENT_PAST_YEARS = 19  # 所令70①：前年以前4年内（iDeCo の一時金があれば9年内・19年内）。一番長い19年で検出する


def retire_year(r: Mapping[str, Any], group: list[Mapping[str, Any]] | None = None) -> int:
    """退職手当等の収入すべき時期の年（taishoku §1.2 の TA2728・所令77、所基通36−10 の本文）。

    - 一の勤務先の退職で2以上の退職手当等の支払を受けるとき（同じ支払者・同じ退職日の記録が2件以上）：最初に支払を受けるべきものの支払の日の年（所令77）。
    - 役員の退職手当等で決議を要するもの（resolution_on あり）：決議の日（TA2728。金額が具体的に定められた日は語彙がないので決議の日と読む）。
    - それ以外：その支給の基因となった退職の日（retired_on）。なければ支払日（when.on）。
    """
    if group is not None and len(group) > 1:
        return min(_date(g["when"]["on"]) for g in group).year
    a = r["attributes"]
    if a.get("resolution_on"):
        return _date(a["resolution_on"]).year
    return _year_of(r, "retired_on")


def _retire_groups(ctx: YearContext, pid: str) -> dict[str, list[Mapping[str, Any]]]:
    """記録の ID → 同じ支払者・同じ退職日の退職手当等の記録（所令77 の「一の勤務先を退職することにより二以上の」）。退職日のない記録は1件ずつ。"""
    by: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for r in ctx.records("retirement_payment"):
        if r["roles"]["recipient"] != pid:
            continue
        a = r["attributes"]
        key = (a.get("counterparty"), a["retired_on"]) if a.get("retired_on") else ("", r["id"])
        by.setdefault(key, []).append(r)
    return {r["id"]: g for g in by.values() for r in g}


def _retirement_payments(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    groups = _retire_groups(ctx, pid)
    return sorted(
        (r for r in ctx.records("retirement_payment") if r["roles"]["recipient"] == pid and retire_year(r, groups[r["id"]]) == ctx.year),
        key=lambda r: r["id"],
    )


def service_years(start: _dt.date, end: _dt.date) -> int:
    """勤続年数（所令69①一・②、所基通30−13）：start〜end（両端を含む）を暦に従って数え、1年未満の端数は1年。"""
    if end < start:
        raise ValueError("勤務期間の終わりが始まりより前")
    stop = end + _dt.timedelta(days=1)  # 両端を含むので、翌日までの満の年数を数える
    years = stop.year - start.year
    if (stop.month, stop.day) < (start.month, start.day):
        years -= 1
    exact = _add_months(start, 12 * years) == stop
    return max(1, years + (0 if exact else 1))


def _paid_in_year(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """その年に支払われた（when.on の年）退職手当等の支払。給与とした支払の年分（所基通36−9(1)：IK-25）の材料。"""
    return sorted(
        (r for r in ctx.records("retirement_payment") if r["roles"]["recipient"] == pid and _date(r["when"]["on"]).year == ctx.year),
        key=lambda r: r["id"],
    )


def _retire_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    for pid in ctx.persons:
        pays = _retirement_payments(ctx, pid)
        # 退職の日の年分と支払の日の年が違う支払も、給与とした判断があればその支払の日の年分で読む（IK-25）。退職の年分の支払がない年は、
        # 給与とした判断があるときだけ読む（読んだときだけ開く）
        paid = _paid_in_year(ctx, pid)
        if not pays and not paid:
            continue
        ids = frozenset(r["id"] for r in [*pays, *paid])
        out.append(
            DecisionSlot(
                key=pid,
                target={"person": pid, "payment_ids": sorted(ids), "tax_year": ctx.year},
                matches=lambda rec, ids=ids: rec["subject"]["payment_id"] in ids,
                candidates=(
                    Candidate({"is_retirement_allowance": True, "disability_retirement": False}, "障害退職でない"),
                    Candidate({"is_retirement_allowance": True, "disability_retirement": True}, "障害退職"),
                ),
                lazy=not pays,
            )
        )
    return out


def _retire_salary(ctx: YearContext, out: ModuleInputs) -> None:
    """判断.退職の性質 で退職手当等に当たらず給与（income_type: salary）とした支払の額（IK-25。RETIRE_AS_SALARY_RULE）。

    年分は支払の日（when.on）の年（所基通36−9(1) の支給を受けた日。支給日の定めの欄がない：法令の読み）。受給者の死亡の日以後の支払は、
    支給期が死亡の前か（所基通9−17）が支給日の定めで決まるので、額に入れて分かれ目（事実）を付ける（kyuyo の死亡後の給与と同じ扱いの材料がない）。
    未入力の判断は退職手当等に当たる候補だけで評価する（今のまま）ので、給与とした判断が入力されたときだけ数える。
    """
    for pid in ctx.persons:
        paid = _paid_in_year(ctx, pid)
        if not paid:
            out.set(V_RETIRE_SALARY, pid, 0)
            continue
        ids = {r["id"] for r in paid}
        in_retire_year = bool(_retirement_payments(ctx, pid))
        salary_judged = any(
            j["subject"]["payment_id"] in ids and isinstance(j.get("value"), Mapping) and j["value"].get("income_type") == "salary"
            for j in ctx.judgments(K_RETIRE)
        )
        if not in_retire_year and not salary_judged:
            out.set(V_RETIRE_SALARY, pid, 0)
            continue
        d = ctx.decision(K_RETIRE, pid)
        v = d.value if isinstance(d.value, Mapping) else {}
        if not (v.get("is_retirement_allowance") is False and v.get("income_type") == "salary"):
            out.set(V_RETIRE_SALARY, pid, 0, d.record_ids, d.states)
            continue
        total = sum(r["amounts"]["gross"] for r in paid)
        _check_amount(total, "退職手当等に当たらないとした給与等の収入金額")
        death = ctx.death_on(pid)
        miss: list[Split] = []
        after = [r["id"] for r in paid if death is not None and _date(r["when"]["on"]) >= death]
        if after:
            miss.append(undetermined(
                f"事実:給与とした退職手当等の支払の支給期:{pid}:{ctx.year}", Means.FACT,
                {"person": pid, "payment_ids": after,
                 "入力": "受給者の死亡の日以後に支払われた、給与とした退職手当等の支給日の定め（retirement_payment に支給日の欄がない。所基通9−17・36−9）"},
                ("支給期が死亡の前（所得税に入れる）", "支給期が死亡の後（所得税に入れない）"),
            ))
        if total > INT32_MAX:
            out.exclude(pid, _reason("退職手当等に当たらないとした給与等の収入金額が判定コアの整数の範囲を超える", sorted(ids)), V_RETIRE_SALARY)
            total = 0
        out.set(V_RETIRE_SALARY, pid, total, sorted(ids) + list(d.record_ids), _states(paid) | set(d.states), basis=[RETIRE_AS_SALARY_RULE], missing=miss)


TAISHOKU_DOC = "docs/public-sources/20261109_round2b_taishoku-laws-and-guidance.md"
DEATH_RETIREMENT_RULE = BasisEntry(
    type=BasisType.RULE,
    name="死亡退職により死亡の日以後に支払われる退職手当等は所得税の対象にしない（相続税の課税の対象）",
    source_kind=SourceKind.NTA_EXPLANATION,
    law="タックスアンサー No.2732（根拠法令等に所法9）・所得税基本通達9−17。相続税の課税価格の確認は要しないものとして読む（kyuyo の死亡後の給与と同じ読み：D22 S10）",
    references=(f"{TAISHOKU_DOC}#1.2", "docs/public-sources/20261111_impl-research_kyuyo-jiki-laws-and-nta.md#2.2"),
    flags=(ReadingFlag.LEGAL_READING,),
)


CONTRIBUTION_RULE = BasisEntry(
    type=BasisType.RULE,
    name="在職中に使用者に掛金を拠出して退職に際して支払われる一時金は、受給者が拠出した掛金（employee_contributions）を控除した額を退職手当等の収入金額とする",
    source_kind=SourceKind.CIRCULAR,
    law="所得税基本通達30−3（原文：scripts/results/R2B_taishoku_web/text/followup_20261109-181612/kihon_04_04.txt）",
    references=(f"{TAISHOKU_DOC}#1.2",),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "employee_contributions は通達の「掛金（支給日までにその掛金の運用益として元本に繰り入れられた金額を含む。）」の額と読む"},
)
RETIRE_DETAIL_VARS = (V_RET_PRIOR_YEARS, V_RET_SHORT_INCOME, V_RET_OFFICER_INCOME, V_RET_SHORT_DED, V_RET_OFFICER_DED)
#: 所令70①二イ：前年以前4年内の退職手当等は、確定拠出年金の老齢給付金の一時金（所令72③七）があるかによらず「前の退職手当等」に当たる。
#: 5年〜19年前のもの（ロ・ハ、令和7年分は改正前の19年内）は所令72③七の一時金かで決まり、それを入力する語彙がない（payment_category は自由な符号）
PRIOR_SURE_YEARS = 4
RETIRE_NOTE_REASON = (
    "勤務期間に中断・前の勤務の注記がある（所令69①一イ〜ハ・70①一：加算・除外する期間は注記〔自由な文字列〕からは計算できない。"
    "retirement_record の attributes.service_adjustments に期間を書けば決まる）"
)
RETIRE_PARTIAL_OFFICER_REASON = (
    "調整後勤続期間のうちに5年以下の役員等勤続期間とそれ以外の期間がある退職手当等（所令71の2⑬）：一般・短期退職手当等の部分の額"
    "（他の使用人に対する退職給与の支給の水準等を勘案して相当と認められる金額）が支払の記録（retirement_payment の amounts.non_officer_portion）にない、"
    "又は支払の額を超える"
)
RETIRE_ADJUST_REASON = "勤続期間の加算・除外（service_adjustments）の期間に終わりの日（to_on）がない、又は除外の後に勤続期間が残らない"
RETIRE_ONE_AND_TWO_REASON = (
    "所令70①一の期間と70①二の重複期間の両方があり、勤続年数とみなした③の額の合計が年数の合計の③の額と違う（20年をまたぐ。"
    "判定コアは控除する年数を1つの入力で持つので、この組合せを計算できない）"
)
SERVICE_ADJUST_RULE = BasisEntry(
    type=BasisType.RULE,
    name="勤続期間の加算・除外（所令69①一イ〜ハ）と、他の者・同じ支払者から前に受けた退職手当等の期間を勤続年数とみなした額の控除（所令70①一・③）",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法施行令第69条第1項第1号イ〜ハ・第70条第1項第1号・第3項",
    references=("docs/public-sources/20261112_impl-a3_taishoku-haito-kyufu.md#1", "docs/public-sources/20261112_impl-a3_taishoku-haito-kyufu.md#2"),
    flags=(ReadingFlag.LEGAL_READING,),
    detail={"note": "ハただし書の前の退職手当等につき所令69①で計算した期間は、記録の prior_allowance_basis の期間と読む"},
)
PARTIAL_OFFICER_RULE = BasisEntry(
    type=BasisType.RULE,
    name="5年以下の役員等勤続期間とそれ以外の期間がある退職手当等は、特定役員退職手当等（全体−相当と認められる金額）と一般・短期退職手当等（相当と認められる金額）から成る",
    source_kind=SourceKind.CABINET_ORDER,
    law="所得税法施行令第71条の2第13項",
    references=("docs/public-sources/20261112_impl-a3_taishoku-haito-kyufu.md#3",),
)


def _adjusted_period(rr: Mapping[str, Any]) -> tuple[list[Interval], list[tuple[int, Interval]], str | None]:
    """調整後の勤続期間（所令69①一イ〜ハ）と、所令70①一の期間（(年数〔70③：1年未満切捨て〕, 期間)）。

    when（退職の日まで引き続き勤務した期間）に、イ（一時勤務しなかった期間前の同じ支払者の下の期間）・ロ（支払金額の計算の基礎に含める他の者の下の期間）を
    加え、ハ（前に受けた退職手当等の計算の基礎とされた期間）の末日以前を除く（ハただし書：今回の計算の基礎に含めるなら除かず、70①一の期間にする）。
    """
    def iv(x: Mapping[str, Any]) -> Interval | None:
        return (_date(x["from_on"]), _date(x["to_on"])) if x.get("to_on") else None

    period = _period_of(rr)
    adds: list[Interval] = []
    one: list[tuple[int, Interval]] = []
    cut: _dt.date | None = None
    for x in rr["attributes"].get("service_adjustments") or []:
        span = iv(x["period"])
        if span is None:
            return [], [], RETIRE_ADJUST_REASON
        if x["type"] == "earlier_service_same_payer":
            adds.append(span)
        elif x["type"] == "other_employer_service":
            adds.append(span)
            if x.get("prior_allowance_period"):
                pp = iv(x["prior_allowance_period"])
                if pp is None:
                    return [], [], RETIRE_ADJUST_REASON
                one.append((years_floor(measure([pp])), pp))
        elif x.get("included_in_payment_basis"):
            one.append((years_floor(measure([span])), span))
        else:
            cut = span[1] if cut is None else max(cut, span[1])
    out = normalize(period + adds)
    if cut is not None:
        out = subtract(out, [(_dt.date.min, cut)])
    if not out:
        return [], [], RETIRE_ADJUST_REASON
    return out, one, None


@dataclass
class RetirePlan:
    """その年分の退職手当等の組み立て（所令69〜71の2）。"""

    total: int = 0
    years: int = 1
    kind: str = RETIRE_GENERAL
    prior_years: int = 0
    short_income: int = 0
    officer_income: int = 0
    short_ded: int = 0
    officer_ded: int = 0
    contributions: bool = False
    records: list[Mapping[str, Any]] = field(default_factory=list)
    prior_ids: tuple[str, ...] = ()
    problems: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    missing: list[Any] = field(default_factory=list)
    adjusted: bool = False  # 勤続期間の加算・除外（service_adjustments）を使った
    partial: bool = False  # 所令71の2⑬ で分けた
    prior_one: list[int] = field(default_factory=list)  # 所令70①一の期間の年数（70③：1年未満切捨て）
    one_periods: list[Interval] = field(default_factory=list)  # 所令70①一の前の退職手当等の期間（70①二の前の退職手当等から除く）


def _record_for(ctx: YearContext, pid: str, payer: Any, years: tuple[int, ...]) -> list[Mapping[str, Any]]:
    """退職の申告書と勤務期間の記録のうち、支払者（counterparty）と退職の年が合うもの。payer が None なら年だけで選ぶ。"""
    out = []
    for r in ctx.records("retirement_record"):
        if r["roles"]["recipient"] != pid or not r["when"].get("to_on") or _date(r["when"]["to_on"]).year not in years:
            continue
        cp = r["attributes"].get("counterparty")
        if payer is not None and cp is not None and cp != payer:
            continue
        out.append(r)
    return out


def _period_of(rr: Mapping[str, Any]) -> list[Interval]:
    return [(_date(rr["when"]["from_on"]), _date(rr["when"]["to_on"]))]


def _prior_deemed(rr: Mapping[str, Any], income: int, p: Any) -> list[Interval]:
    """前の勤続期間等（所令70②：前の収入金額が前の退職所得控除額〔③の額〕に満たなければ、就職の日から所定の年数を経過した日の前日まで）。"""
    start, end = _date(rr["when"]["from_on"]), _date(rr["when"]["to_on"])
    if income >= _deduction_by_years(years_ceil(ymd(start, end)), p):
        return [(start, end)]
    q = p.所得税.退職所得.前の退職手当等
    if income <= int(q.区分の額):
        k = income // int(q.一年当たりの額)
    else:
        k = (income - int(q.区分の額)) // int(q.区分を超える一年当たりの額) + int(q.区分を超えるときに加算する数)
    if k <= 0:
        return []
    return [(start, min(end, _add_months(start, 12 * k) - _dt.timedelta(days=1)))]


def _retirement_plan(ctx: YearContext, pid: str, pays: list[Mapping[str, Any]], partial_reading: str = "whole") -> RetirePlan:
    """partial_reading：所令71の2⑬ で分けた一般・短期の部分の勤続期間を、調整後勤続期間の全部（whole）とするか、
    役員等勤続期間以外の期間（non_officer）とするか（一次情報なし。_retirement が両方で評価する）。"""
    plan = RetirePlan()
    payer_periods: list[list[Interval]] = []
    p = _LazyParameters(ctx)  # 前の退職手当等・二以上の区分があるときだけ引く
    payers = sorted({r["attributes"].get("counterparty") for r in pays}, key=lambda x: (x is None, x or ""))
    if len(payers) > 1 and None in payers:
        plan.problems.append((
            "その年に2以上の退職手当等の支払があり、支払者（counterparty）の記載がないものがある（支払者ごとの勤続期間〔所令69①三〕を結びつけられない）",
            tuple(r["id"] for r in pays),
        ))
        return plan
    per_payer: list[tuple[str, list[Interval], int]] = []  # (区分, 勤続期間, 収入金額)
    for payer in payers:
        group = [r for r in pays if r["attributes"].get("counterparty") == payer]
        income = 0
        for r in group:
            contrib = r["amounts"].get("employee_contributions", 0)
            if contrib:
                plan.contributions = True
            income += max(0, r["amounts"]["gross"] - contrib)  # 所基通30−3
        plan.total += income
        recs = _record_for(ctx, pid, payer if len(payers) > 1 else None, (ctx.year - 1, ctx.year))
        gids = tuple(r["id"] for r in group)
        if len(recs) != 1:
            plan.problems.append((
                "勤続年数を決める退職の申告書と勤務期間の記録（retirement_record）が支払者ごとに1つでない"
                "（2以上の支払者があるときは counterparty で支払と結びつける）",
                tuple(r["id"] for r in recs) or gids,
            ))
            continue
        rr = recs[0]
        plan.records.append(rr)
        a = rr["attributes"]
        adjs = a.get("service_adjustments") or []
        if (a.get("interruption_note") or a.get("prior_service_note")) and not adjs:
            plan.problems.append((RETIRE_NOTE_REASON, (rr["id"],)))
            continue
        period, one, bad = _adjusted_period(rr)
        if bad is not None:
            plan.problems.append((bad, (rr["id"],)))
            continue
        if adjs:
            plan.adjusted = True
        plan.prior_one += [y for y, _ in one]
        plan.one_periods += [iv for _, iv in one]
        payer_periods.append(period)
        years = years_ceil(measure(period))
        officer = a.get("officer_period")
        if officer:
            o_end = _date(officer["to_on"]) if officer.get("to_on") else period[-1][1]
            o_set = intersect(period, [(_date(officer["from_on"]), o_end)])
            o_years = years_ceil(measure(o_set))
            if not subtract(period, o_set):  # 全部が役員等の期間
                kind = RETIRE_OFFICER if o_years <= OFFICER_SERVICE_LIMIT else RETIRE_GENERAL
            elif o_years <= OFFICER_SERVICE_LIMIT:
                # 所令71の2⑬：特定役員退職手当等（全体−二の額）と、役員等勤続期間以外の期間を基礎として相当と認められる金額の
                # 一般・短期退職手当等から成る。二の額は支払の記録の non_officer_portion（2026-11-12）。短期かは調整後勤続期間の全部で数える（所令69の2③）
                portions = [r["amounts"].get("non_officer_portion") for r in group]
                if any(x is None for x in portions) or sum(portions) > income:
                    plan.problems.append((RETIRE_PARTIAL_OFFICER_REASON, (rr["id"], *gids)))
                    continue
                portion = sum(portions)
                plan.partial = True
                k2 = RETIRE_SHORT if years <= SHORT_SERVICE_LIMIT else RETIRE_GENERAL
                # 一般・短期の部分の勤続期間：調整後勤続期間の全部か、役員等勤続期間以外の期間か（一次情報なし：A3_DOC §4。両方で評価する）
                per_payer.append((RETIRE_OFFICER, o_set, income - portion))
                per_payer.append((k2, period if partial_reading == "whole" else subtract(period, o_set), portion))
                continue
            else:
                # 役員等勤続年数が5年を超えるので特定役員退職手当等でない。短期勤続年数は役員等勤続期間を含めて数える（所令69の2③）
                kind = RETIRE_SHORT if years <= SHORT_SERVICE_LIMIT else RETIRE_GENERAL
        else:
            kind = RETIRE_SHORT if years <= SHORT_SERVICE_LIMIT else RETIRE_GENERAL
        per_payer.append((kind, period, income))
    if plan.problems:
        return plan
    # 勤続年数（所令69①三：最も長い期間に、それと重複していない期間を加算。所基通30−13 で年・月・日を合計）。支払者ごとの調整後の期間で数える
    longest = max(range(len(payer_periods)), key=lambda i: measure(payer_periods[i]))
    parts = [measure(payer_periods[longest])] + [measure(subtract(x, payer_periods[longest])) for i, x in enumerate(payer_periods) if i != longest]
    plan.years = years_ceil(sum_ymd(parts))
    current = normalize(iv for x in per_payer for iv in x[1])
    sets = {k: normalize(iv for x in per_payer if x[0] == k for iv in x[1]) for k in (RETIRE_GENERAL, RETIRE_SHORT, RETIRE_OFFICER)}
    income_of = {k: sum(x[2] for x in per_payer if x[0] == k) for k in sets}
    kinds = [k for k in sets if income_of[k] > 0]
    plan.kind = kinds[0] if len(kinds) == 1 else RETIRE_GENERAL
    # 前の退職手当等（所令70①二・②・③）。所令70①一の前に支払を受けた退職手当等（その期間と重なる記録）は除く
    prior: list[tuple[int, _dt.date, bool | None, list[Interval]]] = []  # (年, 最初の支払日, 老齢一時金か, みなす前の勤続期間等)
    prior_ids: list[str] = []
    groups = _retire_groups(ctx, pid)
    seen: set[str] = set()
    for r in sorted(ctx.records("retirement_payment"), key=lambda r: r["id"]):
        if r["roles"]["recipient"] != pid or r["id"] in seen:
            continue
        g = groups[r["id"]]
        seen |= {x["id"] for x in g}
        y = retire_year(r, g)
        if not (ctx.year - RETIREMENT_PAST_YEARS <= y < ctx.year):
            continue
        income = sum(max(0, x["amounts"]["gross"] - x["amounts"].get("employee_contributions", 0)) for x in g)
        recs = _record_for(ctx, pid, r["attributes"].get("counterparty"), (y,))
        gids = tuple(x["id"] for x in g)
        if len(recs) != 1:
            plan.problems.append((
                "前年以前の退職手当等（所令70）の勤務期間の記録（retirement_record：counterparty と退職の年で結びつける）が1つでない",
                tuple(x["id"] for x in recs) or gids,
            ))
            continue
        prior_ids += [*gids, recs[0]["id"]]
        if plan.one_periods and intersect(_period_of(recs[0]), plan.one_periods):
            continue  # 所令70①二の「前号に規定する前に支払を受けた退職手当等を除く」
        flags = {x["attributes"].get("old_age_dc_lump_sum") for x in g}
        dc = True if True in flags else (None if None in flags else False)
        prior.append((y, min(_date(x["when"]["on"]) for x in g), dc, _prior_deemed(recs[0], income, p)))
    plan.prior_ids = tuple(prior_ids)
    if plan.problems:
        return plan

    def _prior(ivs: list[Interval]) -> tuple[int, int, int]:
        return (
            years_floor(measure(intersect(current, ivs))),
            years_floor(measure(intersect(sets[RETIRE_SHORT], ivs))),
            years_floor(measure(intersect(sets[RETIRE_OFFICER], ivs))),
        )

    # 所令70①二（令和8年分から イ・ロ・ハ。令和7年分は改正前の「四年内（その年に72③七の一時金を受けるなら十九年内）」：令和7年政令第120号附則第4条）
    cur_flags = {x["attributes"].get("old_age_dc_lump_sum") for x in pays}
    cur_opts = [True] if True in cur_flags else ([False, True] if None in cur_flags else [False])
    r8 = _dt.date(2026, 1, 1)
    dc9 = [x for x in prior if ctx.year - x[0] <= 9 and x[1] >= r8]
    dc9_opts = [True] if any(x[2] is True for x in dc9) else ([False, True] if any(x[2] is None for x in dc9) else [False])

    def _window(cur_dc: bool, prior_dc: bool) -> list[Interval]:
        out_: list[Interval] = []
        for y, first, _, ivs in prior:
            age = ctx.year - y
            if cur_dc:
                ok = age <= RETIREMENT_PAST_YEARS  # ハ（改正前も同じ19年内）
            elif ctx.year >= 2026 and prior_dc:
                ok = age <= 9 if first >= r8 else age <= PRIOR_SURE_YEARS  # ロ(1)(2)
            else:
                ok = age <= PRIOR_SURE_YEARS  # イ
            if ok:
                out_.extend(ivs)
        return out_

    results = {(c, q): _prior(_window(c, q)) for c in cur_opts for q in dc9_opts}
    low = results[(cur_opts[0], dc9_opts[0])]
    if len(set(results.values())) > 1:
        plan.missing.append(
            undetermined(
                f"事実:前の退職手当等の範囲:{pid}:{ctx.year}",
                Means.FACT,
                {
                    "person": pid,
                    "prior_ids": list(plan.prior_ids),
                    "入力": "その年・前年以前9年〜19年内の退職手当等が確定拠出年金法の老齢給付金として支給される一時金（所令72③七）か"
                    "（retirement_payment の attributes.old_age_dc_lump_sum。所令70①二ロ・ハ）",
                },
                ("前の退職手当等に含めない", "前の退職手当等に含める"),
            )
        )
    plan.prior_years, prior_short, prior_officer = low
    if plan.prior_one:
        # 所令70①一（他の者・同じ支払者から前に受けた退職手当等の期間を勤続年数とみなした③の額）を、70①二の額とあわせて控除する。
        # 入力変数は年数1つなので、③の額が年数について足し算になる範囲（20年以下の段）でだけ年数を合わせる。超えるなら対象外
        ys = [*plan.prior_one, plan.prior_years]
        if sum(_deduction_by_years(y, p) for y in ys) != _deduction_by_years(sum(ys), p):
            plan.problems.append((RETIRE_ONE_AND_TWO_REASON, tuple(r["id"] for r in plan.records) + plan.prior_ids))
            return plan
        plan.prior_years = sum(ys)
    # 二以上の区分（所令71の2①③⑤⑦。⑪⑫：前の退職手当等と重複する短期・特定役員の期間の分を控除）
    if len(kinds) >= 2:
        n = p.所得税.退職所得
        per = int(n.退職所得控除額.一年当たりの額)
        q = n.二以上の退職手当等
        two, o14, s13 = int(q.重複勤続年数の一年当たりの額), int(q.全重複期間の特定役員の一年当たりの額), int(q.全重複期間の短期の一年当たりの額)
        G, S, O = sets[RETIRE_GENERAL], sets[RETIRE_SHORT], sets[RETIRE_OFFICER]

        def cy(xs: list[Interval]) -> int:  # 所令71の2⑩：1年未満は1年
            return years_ceil(measure(xs))

        allx = intersect(intersect(G, S), O)
        if len(kinds) == 3:
            d_o = cy(subtract(normalize(intersect(O, S) + intersect(O, G)), allx))
            d_s = cy(subtract(normalize(intersect(S, O) + intersect(S, G)), allx))
            d_a = cy(allx)
            plan.officer_ded = per * (cy(O) - d_o - d_a) + two * d_o + o14 * d_a - _deduction_by_years(prior_officer, p)
            plan.short_ded = per * (cy(S) - d_s - d_a) + two * d_s + s13 * d_a - _deduction_by_years(prior_short, p)
        elif income_of[RETIRE_OFFICER]:
            d = cy(intersect(O, S if income_of[RETIRE_SHORT] else G))
            plan.officer_ded = per * (cy(O) - d) + two * d - _deduction_by_years(prior_officer, p)
        else:
            d = cy(intersect(S, G))
            plan.short_ded = per * (cy(S) - d) + two * d - _deduction_by_years(prior_short, p)
        plan.short_income, plan.officer_income = income_of[RETIRE_SHORT], income_of[RETIRE_OFFICER]
    return plan


def _deduction_by_years(years: int, p: Any) -> int:
    return 0 if years == 0 else deduction_by_years(years, retirement_rules(p))


class _LazyParameters:
    """ctx.parameters を最初に属性を引いたときに読む。"""

    def __init__(self, ctx: YearContext) -> None:
        self._ctx = ctx

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx.parameters, name)


def _set_no_detail(out: ModuleInputs, pid: str) -> None:
    for v in RETIRE_DETAIL_VARS:
        out.set(v, pid, 0)


def _retirement(ctx: YearContext, out: ModuleInputs) -> None:
    for pid in ctx.persons:
        pays = _retirement_payments(ctx, pid)
        slip = [
            r["id"]
            for r in ctx.records("withholding_slip")
            if r["roles"]["recipient"] == pid and r["attributes"]["slip_type"] == "retirement" and r["when"]["tax_year"] == ctx.year
        ]
        variables = (V_RET_INCOME, V_RET_YEARS, V_RET_KIND, V_RET_DISABLED)
        if not pays:
            if slip:
                for v in variables:
                    out.exclude(pid, _reason("退職所得の源泉徴収票があるのに、その年分の退職手当等の支払の記録がない", slip), v)
            out.set(V_RET_INCOME, pid, 0, slip)
            out.set(V_RET_YEARS, pid, 1)
            out.set(V_RET_KIND, pid, RETIRE_GENERAL)
            out.set(V_RET_DISABLED, pid, False)
            out.set(V_RET_WITHHOLD, pid, 0, slip)
            _set_no_detail(out, pid)
            continue
        problems: list[tuple[str, tuple[str, ...]]] = []
        death_basis = False
        pay_ids = tuple(r["id"] for r in pays)
        _check_amount(sum(r["amounts"]["gross"] for r in pays), "退職手当等の収入金額")
        death = ctx.death_on(pid)
        if death is not None:
            # 死亡退職（退職の日が死亡の日）で死亡の日以後に支払われる退職手当等は相続税の課税の対象で、所得税の対象にしない（TA2732・所基通9−17）。
            # 退職の日が死亡の前なら本人の退職所得（支給期は退職の日：36−10）。退職の日の記録がなければ決められない
            after = [r for r in pays if _date(r["when"]["on"]) >= death]
            unknown = [r["id"] for r in after if not r["attributes"].get("retired_on")]
            if unknown:
                problems.append(("受給者の死亡の日以後の退職手当等の支払で、退職の日（retired_on）の記録がない（死亡退職で相続税の対象か決まらない：TA2732）", tuple(unknown)))
            death_retire = [r for r in after if r["attributes"].get("retired_on") and _date(r["attributes"]["retired_on"]) >= death]
            if death_retire:
                pays = [r for r in pays if r not in death_retire]
                death_basis = True
                if not pays:
                    out.set(V_RET_INCOME, pid, 0, [r["id"] for r in death_retire], _states(death_retire), basis=[DEATH_RETIREMENT_RULE])
                    out.set(V_RET_YEARS, pid, 1)
                    out.set(V_RET_KIND, pid, RETIRE_GENERAL)
                    out.set(V_RET_DISABLED, pid, False)
                    out.set(V_RET_WITHHOLD, pid, 0, [r["id"] for r in death_retire])
                    _set_no_detail(out, pid)
                    continue
                pay_ids = tuple(r["id"] for r in pays)

        plan = _retirement_plan(ctx, pid, pays)
        problems += plan.problems
        if plan.partial and not plan.problems:
            # 所令71の2⑬ の一般・短期の部分の勤続期間の読み（調整後勤続期間の全部か、役員等勤続期間以外の期間か）。一次情報がないので両方で評価し、
            # 入力が分かれれば未確定（D22 S1。決める手段は一次情報）。値は全部の期間の読み
            alt = _retirement_plan(ctx, pid, pays, "non_officer")
            key = lambda q: (q.years, q.kind, q.prior_years, q.short_income, q.officer_income, q.short_ded, q.officer_ded, tuple(q.problems))  # noqa: E731
            if key(alt) != key(plan):
                plan.missing.append(undetermined(
                    f"一次情報:所令71の2⑬の一般・短期の部分の勤続期間:{pid}:{ctx.year}", Means.PRIMARY_SOURCE,
                    {"person": pid, "payment_ids": list(pay_ids),
                     "入力": "所令71の2⑬二の一般・短期退職手当等の部分の勤続期間を、調整後勤続期間の全部とするか役員等勤続期間以外の期間とするか（docs に一次情報がない）"},
                    ("調整後勤続期間の全部", "役員等勤続期間以外の期間"),
                ))
        d = ctx.decision(K_RETIRE, pid)
        value = d.value if isinstance(d.value, Mapping) else {}
        missing: list[Split] = list(plan.missing)
        if value.get("is_retirement_allowance") is False and value.get("income_type") in ("occasional", "salary"):
            # 退職手当等に当たらず一時所得とした支払（2026-11-12：判断の income_type）。_windfall が一時所得の総収入金額に数える。
            # 給与とした支払は _retire_salary が支払の日の年分の 所得税_退職手当等に当たらないとした給与等の収入金額 にする（kyuyo が足す：IK-25）。退職所得は0
            ids0 = list(pay_ids) + list(d.record_ids)
            st0 = _states(pays) | set(d.states)
            rule = RETIRE_AS_WINDFALL_RULE if value.get("income_type") == "occasional" else RETIRE_AS_SALARY_RULE
            out.set(V_RET_INCOME, pid, 0, ids0, st0, basis=[rule])
            out.set(V_RET_YEARS, pid, 1)
            out.set(V_RET_KIND, pid, RETIRE_GENERAL)
            out.set(V_RET_DISABLED, pid, False)
            _set_no_detail(out, pid)
            # 源泉徴収された税額は、所得の種類によらず精算する額として残す
            slips0 = [r for r in ctx.records("withholding_slip") if r["roles"]["recipient"] == pid and r["attributes"]["slip_type"] == "retirement" and r["when"]["tax_year"] == ctx.year]
            _withhold_from_records(out, ctx, pid, V_RET_WITHHOLD, pays, slips0, "退職手当等の支払", False)
            continue
        if value.get("is_retirement_allowance") is False:
            # 退職手当等に当たらないとした支払で、所得の種類（income_type）が未入力：給与所得（所基通30−1）か一時所得かで所得が分かれるので、
            # 退職所得の側を未確定にする（D21 R6。給与・一時所得なら上で決まる：IK-25）
            missing.append(undetermined(f"事実:退職手当等でない支払の所得の種類:{pid}:{ctx.year}", Means.FACT, {
                "person": pid, "payment_ids": list(pay_ids), "入力": "判断.退職の性質 の income_type（salary か occasional）"}))
        oc = value.get("officer_class")
        if oc is not None and len(plan.records) == 1:
            officer_fact = bool(plan.records[0]["attributes"].get("officer_period"))
            has_officer = plan.kind == RETIRE_OFFICER or plan.officer_income > 0  # 所令71の2⑬ で分けたときは特定役員の部分を含む
            if (oc == "specified_officer") != has_officer or (oc == "none" and officer_fact) or (
                oc == "general_officer" and (not officer_fact or has_officer)
            ):
                problems.append(("判断.退職の性質の役員の区分が勤務期間の記録（officer_period）と合わない", d.record_ids))
        disabled = bool(value.get("disability_retirement", False))
        total = plan.total
        if total > INT32_MAX:
            problems.append(("退職手当等の収入金額が判定コアの整数の範囲を超える", pay_ids))
        rec_ids = tuple(r["id"] for r in plan.records) + plan.prior_ids
        ids = list(pay_ids) + list(rec_ids)
        st = _states(pays) | _states(plan.records) | set(d.states)
        excluded = bool(problems)
        for text, pids in problems:
            for v in (*variables, *RETIRE_DETAIL_VARS):
                out.exclude(pid, _reason(text, pids), v)
        miss = tuple(missing)
        basis = (
            ([DEATH_RETIREMENT_RULE] if death_basis else [])
            + ([CONTRIBUTION_RULE] if plan.contributions else [])
            + ([SERVICE_ADJUST_RULE] if plan.adjusted or plan.prior_one else [])
            + ([PARTIAL_OFFICER_RULE] if plan.partial else [])
        )
        out.set(V_RET_INCOME, pid, 0 if excluded else total, ids, st, basis=basis, missing=miss)
        out.set(V_RET_YEARS, pid, max(1, plan.years) if not excluded else 1, ids, st, missing=miss)
        out.set(V_RET_KIND, pid, plan.kind if not excluded else RETIRE_GENERAL, ids, st)
        out.set(V_RET_DISABLED, pid, disabled and not excluded, list(d.record_ids) + ids, st | set(d.states))
        out.set(V_RET_PRIOR_YEARS, pid, 0 if excluded else plan.prior_years, ids, st, missing=miss)
        out.set(V_RET_SHORT_INCOME, pid, 0 if excluded else plan.short_income, ids, st)
        out.set(V_RET_OFFICER_INCOME, pid, 0 if excluded else plan.officer_income, ids, st)
        multi_basis = (
            [
                ctx.parameter_basis(n)
                for n in (
                    "所得税.退職所得.退職所得控除額.一年当たりの額",
                    "所得税.退職所得.二以上の退職手当等.重複勤続年数の一年当たりの額",
                    "所得税.退職所得.二以上の退職手当等.全重複期間の特定役員の一年当たりの額",
                    "所得税.退職所得.二以上の退職手当等.全重複期間の短期の一年当たりの額",
                )
            ]
            if plan.short_ded or plan.officer_ded
            else []
        )
        out.set(V_RET_SHORT_DED, pid, 0 if excluded else plan.short_ded, ids, st, basis=multi_basis, missing=miss)
        out.set(V_RET_OFFICER_DED, pid, 0 if excluded else plan.officer_ded, ids, st, basis=multi_basis, missing=miss)
        slip_recs = [r for r in ctx.records("withholding_slip") if r["roles"]["recipient"] == pid and r["attributes"]["slip_type"] == "retirement" and r["when"]["tax_year"] == ctx.year]
        _withhold_from_records(out, ctx, pid, V_RET_WITHHOLD, pays, slip_recs, "退職手当等の支払", excluded)


# ---------------------------------------------------------------------------
# 事業所得・業務に係る雑所得・不動産所得（必要経費の振分け、消費税等、減価償却、専従者）
# ---------------------------------------------------------------------------

#: 業務の支出の費目のうち、支出が配当所得の負債の利子であることを示す費目（語彙の補い：expense_category は自由な文字列。README の「足りない窓口」）。
DIVIDEND_INTEREST_CATEGORIES = frozenset({"dividend_debt_interest"})
#: 不動産所得の必要経費の費目のうち借入金の利子を示す費目（土地等の負債の利子の判定に使う）。
INTEREST_CATEGORIES = frozenset({"loan_interest", "interest"})
LAND_PROPERTY_TYPES = frozenset({"land", "parking"})

SIDES = ("biz", "misc", "rental")


def _on_year(rec: Mapping[str, Any]) -> int:
    return _year_of(rec, "incurred_on")


def _activity(ctx: YearContext) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
    """人 → 業務の ID → その年分の売上・支出・給与の支払の記録。配当の負債の利子の支出は除く。"""
    out: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for kind, role in (("business_receipt", "recipient"), ("business_expense", "payer"), ("payroll_paid", "employer")):
        for rec in ctx.records(kind):
            if _on_year(rec) != ctx.year:
                continue
            if kind == "business_expense" and rec.get("attributes", {}).get("expense_category") in DIVIDEND_INTEREST_CATEGORIES:
                continue
            bid = rec.get("attributes", {}).get("business_id", "")
            out.setdefault(rec["roles"][role], {}).setdefault(bid, []).append(rec)
    return out


def _owner(ctx: YearContext) -> dict[str, str]:
    return {r["id"]: r["roles"]["owner"] for r in ctx.records("business")}


RENTAL_KINDS = (("rental_property", "owner"), ("lease", "lessor"), ("rent_flow", "recipient"), ("rental_inventory", "owner"))


def _has_rental(ctx: YearContext, pid: str) -> bool:
    return any(
        r["roles"].get(role) == pid and overlaps_year(r.get("when"), ctx.year)
        for kind, role in RENTAL_KINDS
        for r in ctx.records(kind)
    )


def _person_bids(ctx: YearContext) -> dict[str, list[str]]:
    """人 → その年分に見る業務の ID（活動か資産のある業務で、その人が持つもの）。"""
    owners = _owner(ctx)
    out: dict[str, set[str]] = {}
    for pid, by_biz in _activity(ctx).items():
        for bid in by_biz:
            if bid and owners.get(bid) == pid:
                out.setdefault(pid, set()).add(bid)
    for a in ctx.records("depreciable_asset"):
        bid = a["attributes"].get("business_id")
        pid = a["roles"]["owner"]
        if bid and owners.get(bid) == pid and placed_year(a) <= ctx.year:
            out.setdefault(pid, set()).add(bid)
    for r in ctx.records("business_engagement"):
        bid = r["attributes"]["business_id"]
        pid = r["roles"]["business_owner"]
        if owners.get(bid) == pid and overlaps_year(r.get("when"), ctx.year):
            out.setdefault(pid, set()).add(bid)
    # 棚卸し（その年の期末・期首と前年の期末）・家事消費等・貸倒れ（損失の日の年分か、収入金額を算入した年分）の業務（IK-108〜IK-110）
    for kind, role in (("inventory_count", "owner"), ("household_consumption", "owner"), ("bad_debt", "creditor")):
        for r in ctx.records(kind):
            bid = r["attributes"]["business_id"]
            pid = r["roles"][role]
            y = _year_of(r)
            hit = y == ctx.year or (kind == "inventory_count" and y == ctx.year - 1) or (kind == "bad_debt" and r["attributes"].get("revenue_tax_year") == ctx.year)
            if hit and owners.get(bid) == pid:
                out.setdefault(pid, set()).add(bid)
    # その年に受け取った報酬で源泉徴収税額のあるもの（売上の年分が前年でも、第一表 60 の所得の区分を決めるため：IK-111）
    for r in ctx.records("business_receipt"):
        bid = r["attributes"]["business_id"]
        pid = r["roles"]["recipient"]
        if r["amounts"].get("withholding_tax") and _date(r["when"]["on"]).year == ctx.year and owners.get(bid) == pid:
            out.setdefault(pid, set()).add(bid)
    # 貸付けの記録がある人は、活動のない業務（不動産の業務の登録だけのもの）も見る（簿記の判断の1か所のため）
    for r in ctx.records("business"):
        pid = r["roles"]["owner"]
        if pid in ctx.persons and overlaps_year(r.get("when"), ctx.year) and _has_rental(ctx, pid):
            out.setdefault(pid, set()).add(r["id"])
    return {p: sorted(v) for p, v in out.items() if p in ctx.persons}


def placed_year(asset: Mapping[str, Any]) -> int:
    return _date(asset["attributes"].get("placed_in_service_on") or asset["when"]["from_on"]).year


def _rental_bids(ctx: YearContext) -> dict[str, set[str]]:
    """人 → 不動産所得の業務の ID。貸付けの記録がある人の、その年分に売上（business_receipt）のない業務を不動産所得の業務と読む（中間表現に業務と物件の結びつきがない：README）。"""
    act = _activity(ctx)
    out: dict[str, set[str]] = {}
    for pid, bids in _person_bids(ctx).items():
        if not _has_rental(ctx, pid):
            continue
        for bid in bids:
            if not any(r["kind"] == "business_receipt" for r in act.get(pid, {}).get(bid, [])):
                out.setdefault(pid, set()).add(bid)
    return out


def _jigyo_slots(ctx: YearContext) -> list[DecisionSlot]:
    rentals = _rental_bids(ctx)
    out = []
    for pid, bids in sorted(_person_bids(ctx).items()):
        for bid in bids:
            if bid in rentals.get(pid, ()):
                continue
            out.append(
                DecisionSlot(
                    key=f"{pid}:{bid}",
                    target={"person": pid, "business_id": bid, "tax_year": ctx.year},
                    matches=lambda rec, pid=pid, bid=bid: rec["subject"]["person"] == pid and rec["subject"]["business_id"] == bid,
                )
            )
    return out


def _home_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    owners = _owner(ctx)
    for pid, by_biz in sorted(_activity(ctx).items()):
        if pid not in ctx.persons or not any(r["kind"] == "business_receipt" for bid, rs in by_biz.items() if owners.get(bid) == pid for r in rs):
            continue
        out.append(
            DecisionSlot(
                key=pid,
                target={"person": pid, "tax_year": ctx.year},
                matches=lambda rec, pid=pid: rec["subject"]["person"] == pid,
            )
        )
    return out


def _rent_scale_slots(ctx: YearContext) -> list[DecisionSlot]:
    return [
        DecisionSlot(
            key=pid,
            target={"person": pid, "tax_year": ctx.year},
            matches=lambda rec, pid=pid: rec["subject"]["person"] == pid,
        )
        for pid in ctx.persons
        if _has_rental(ctx, pid)
    ]


def _partner_arrangements(ctx: YearContext, pid: str) -> list[str]:
    """その人のその年分の、組合契約に基づく組合事業の物件（rental_property の held_through が partnership_contract）の組合契約の識別。"""
    return sorted(
        {
            str(r["attributes"]["arrangement_id"])
            for r in ctx.records("rental_property")
            if r["roles"]["owner"] == pid
            and overlaps_year(r.get("when"), ctx.year)
            and r["attributes"].get("held_through") == "partnership_contract"
            and r["attributes"].get("arrangement_id")
        }
    )


def _partner_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.組合の重要業務の執行（人 × 組合契約。読んだときだけ開く：組合事業の損失があるときだけ結論に効く。措令26の6の2②③）。"""
    return [
        DecisionSlot(
            key=f"{pid}:{arr}",
            target={"person": pid, "arrangement_id": arr, "tax_year": ctx.year},
            matches=lambda rec, pid=pid, arr=arr: rec["subject"]["person"] == pid and rec["subject"]["arrangement_id"] == arr,
            persons=(pid,),
            lazy=True,
        )
        for pid in ctx.persons
        for arr in _partner_arrangements(ctx, pid)
    ]


def _foreign_used_building(ctx: YearContext, asset: Mapping[str, Any]) -> tuple[bool, str | None]:
    """国外の賃貸物件の減価償却資産が国外中古建物か（措法41の4の3②一・措規18の24の2①）：(当たるか, 決まらない理由)。

    中古（prior_use_months か useful_life_method が見積り・簡便法）の建物で、耐用年数を簡便法（耐用年数省令3①二。判断の耐用年数の年数がなく、
    表の行と prior_use_months で計算するものを含む）か、書類で確かめられない見積り（3①一）で算定したもの。"""
    j = dep_class(ctx, asset["id"])
    value = j["value"] if j is not None else {}
    method = value.get("useful_life_method")
    used = bool(asset["attributes"].get("prior_use_months")) or method in ("estimated_remaining", "simplified")
    if not used:
        return False, None
    cls = value.get("asset_class")
    row = str(value.get("useful_life_table_row") or "")
    if cls is None and not row:
        return False, rsp.FOREIGN_USED_CLASS_REASON
    building = cls == "building" or (cls is None and row.startswith("建物"))
    if not building:
        return False, None
    if method is None:
        if value.get("useful_life_years") is None and row:
            return True, None  # 表の行と prior_use_months から簡便法で計算している（assets.useful_life）
        return False, rsp.FOREIGN_USED_METHOD_REASON
    if method == "legal":
        return False, None
    if method == "simplified":
        return True, None
    if value.get("remaining_life_documented") is None:
        return False, rsp.FOREIGN_USED_METHOD_REASON
    return not value["remaining_life_documented"], None


def _special_rental(ctx: YearContext, pid: str, s: _Sides) -> tuple[rsp.Deemed, set[str], list[tuple[str, tuple[str, ...]]], list[Split]]:
    """組合事業・信託（措法41の4の2）と国外中古建物（措法41の4の3）の不動産所得の損失のうち生じなかったものとみなす金額（IK-104）。
    (金額, 使った記録, 問題 (理由, 記録), 分かれ目)。どちらの物件もなければ0。"""
    none = rsp.Deemed({}, 0)
    props = {r["id"]: r for r in ctx.records("rental_property") if r["roles"]["owner"] == pid and overlaps_year(r.get("when"), ctx.year)}
    special = {k for k, r in props.items() if r["attributes"].get("held_through") or (r["attributes"].get("country_code") or "JP") != "JP"}
    if not special:
        return none, set(), [], []
    ids = set(special)
    problems: list[tuple[str, tuple[str, ...]]] = []
    splits: list[Split] = []
    # 物件の区分
    kinds: dict[str, tuple[str, str | None, bool]] = {}
    building_dep: dict[str, int] = {}
    for k, r in props.items():
        a = r["attributes"]
        if a.get("held_through"):
            arr = a.get("arrangement_id")
            if not arr:
                problems.append((rsp.PARTNERSHIP_ARRANGEMENT_REASON, (k,)))
                continue
            if a["held_through"] == "trust":
                kinds[k] = (rsp.ARRANGEMENT, f"trust:{arr}", True)
            else:
                kinds[k] = (rsp.ARRANGEMENT, f"partnership:{arr}", True)  # 特定組合員かは損失があるときだけ判断を読む（下）
            continue
        if (a.get("country_code") or "JP") == "JP":
            kinds[k] = (rsp.DOMESTIC, None, False)
            continue
        fub = 0
        is_fub = False
        for asset in ctx.records("depreciable_asset"):
            if asset["roles"]["owner"] != pid or asset["attributes"].get("property_id") != k:
                continue
            hit, why = _foreign_used_building(ctx, asset)
            if why is not None:
                problems.append((why, (asset["id"], k)))
            if hit:
                is_fub = True
                fub += s.asset_dep.get(asset["id"], (0, 0))[0]
                ids.add(asset["id"])
        kinds[k] = (rsp.FOREIGN_USED if is_fub else rsp.FOREIGN_OTHER, None, False)
        building_dep[k] = fub
    if problems:
        return none, ids, problems, splits
    # 物件ごとの収支（物件に結びつかない収支があれば区分できない）
    leases = {r["id"]: r for r in ctx.records("lease")}
    rev: dict[str, int] = {}
    unlinked = []
    for r in ctx.records("rent_flow"):
        if r["roles"]["recipient"] != pid or _year_of(r) != ctx.year or r["attributes"]["flow_type"] not in RENT_INCOME_FLOWS:
            continue
        pk = r["attributes"].get("property_id") or leases.get(r["attributes"].get("lease_id", ""), {}).get("attributes", {}).get("property_id")
        if pk not in props:
            unlinked.append(r["id"])
            continue
        rev[pk] = rev.get(pk, 0) + r["amounts"]["amount"]
    attributed = (
        not unlinked
        and sum(rev.values()) == s.rev["rental"]
        and sum(v for k, v in s.prop_exp.items() if k) == s.exp["rental"]
        and sum(v for k, v in s.prop_dep.items() if k) == s.dep["rental"]
        and not ({k for k in s.prop_exp if k} | {k for k in s.prop_dep if k}) - set(props)
    )
    if not attributed:
        return none, ids, [(rsp.PARTNERSHIP_UNATTRIBUTED_REASON, tuple(sorted(special | set(unlinked))))], splits
    units: list[rsp.Unit] = []
    for k, (kind, arr, specified) in kinds.items():
        net = rev.get(k, 0) - s.prop_exp.get(k, 0) - s.prop_dep.get(k, 0)
        units.append(rsp.Unit(k, kind, net, building_dep.get(k, 0), arr, specified))
    # 組合契約の組合事業で損失があるものだけ、特定組合員か（判断.組合の重要業務の執行。真なら特定組合員でない）を読む
    nets: dict[str, int] = {}
    for u in units:
        if u.arrangement is not None:
            nets[u.arrangement] = nets.get(u.arrangement, 0) + u.net
    executes: dict[str, bool] = {}
    for arr, n in nets.items():
        if n < 0 and arr.startswith("partnership:"):
            d = ctx.decision(K_PARTNER, f"{pid}:{arr.split(':', 1)[1]}")
            executes[arr] = bool(d.value)
            ids |= set(d.record_ids)
    units = [rsp.Unit(u.key, u.kind, u.net, u.building_dep, u.arrangement, not executes.get(u.arrangement or "", False)) for u in units]
    result = rsp.deemed(units)
    if result.total and (s.salary["rental"] or s.deduction["rental"]):
        # 専従者給与・事業専従者控除は共通の必要経費で、物件への配分の基準（措令26の6の3③三・措規18の24の2③：合理的な基準）を書く語彙がない。
        # 物件に配分しない（国内の物件の分とする）値を書き、分かれ目にする
        splits.append(undetermined(
            f"判断:専従者給与の物件への配分:{pid}:{ctx.year}", Means.JUDGMENT,
            {"person": pid, "property_ids": sorted(special), "事項": "専従者給与・事業専従者控除の、組合事業・国外中古建物の物件への配分（合理的な基準）"},
            ("配分しない", "収入金額の比で配分"),
        ))
    return result, ids, [], splits


def _is_family_salary(r: Mapping[str, Any]) -> bool:
    return r["kind"] == "payroll_paid" and r["attributes"]["pay_type"] == "family_employee_salary"


def _related_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.業務関連性（支出1件ごと）。未入力の1か所は人ごとの単調な群で両端（全部 true・全部 false）だけを評価する（D21 R6。2026-11-11：「全額を必要経費」の読みをやめた）。

    家事関連費の按分の判断がある支出は、その判断が業務の部分を決めるので関連性の1か所を作らない（按分の判断と関連性の判断の両方があれば関連性も読む）。
    """
    owners = _owner(ctx)
    shared = {
        rid
        for j in ctx.judgments(K_SHARE)
        if j["value"]["purpose"] == "household_expense_business_share"
        for rid in j["subject"].get("record_ids", [])
    }
    judged = {j["subject"]["record_id"] for j in ctx.judgments(K_RELATED)}
    out = []
    for pid, by_biz in sorted(_activity(ctx).items()):
        if pid not in ctx.persons:
            continue
        for bid, recs in sorted(by_biz.items()):
            if not bid or owners.get(bid) != pid:
                continue
            for r in sorted(recs, key=lambda r: r["id"]):
                if r["kind"] == "business_receipt" or _is_family_salary(r):
                    continue
                rid = r["id"]
                if rid in shared and rid not in judged:
                    continue
                out.append(
                    DecisionSlot(
                        key=rid,
                        target={"record_id": rid},
                        matches=lambda rec, rid=rid: rec["subject"]["record_id"] == rid,
                        persons=(pid,),
                        monotone=f"業務関連性:{pid}",
                    )
                )
    return out


def _share_key(rec: Mapping[str, Any]) -> str:
    s = rec["subject"]
    ids = ",".join(sorted(s.get("record_ids", [])))
    return f"{s['person']}:{rec['value']['purpose']}:{s.get('business_id', '')}:{ids}"


SHARE_PURPOSES = ("household_expense_business_share", "asset_business_share", "family_use_share")


def _share_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.按分の割合：その年分の判断があるものだけ（按分は家事関連費の支出と家事兼用の資産にだけ要り、どれが按分の対象かは判断の側で決まる）。"""
    keys = sorted(
        {
            _share_key(j)
            for j in ctx.judgments(K_SHARE)
            if j["value"]["purpose"] in SHARE_PURPOSES and overlaps_year(j.get("when"), ctx.year) and j["subject"]["person"] in ctx.persons
        }
    )
    return [DecisionSlot(key=k, target={"key": k, "tax_year": ctx.year}, matches=lambda rec, k=k: _share_key(rec) == k) for k in keys]


def _blue_candidates(ctx: YearContext) -> set[str]:
    """承認がありうる人（承認の通知か申請の記録がある人）。"""
    return {
        r["roles"]["person"]
        for r in ctx.records("blue_return_procedure")
        if r["attributes"]["procedure"] in ("approval_notice", "application_filed")
    }


def _simplified_books(ctx: YearContext, pid: str, bid: str) -> bool:
    return any(
        r["roles"]["person"] == pid
        and r["when"]["tax_year"] == ctx.year
        and r["attributes"].get("business_id") in (bid, None)
        and r["attributes"]["bookkeeping_method"] != "double_entry"
        for r in ctx.records("bookkeeping_status")
    )


def _book_slots(ctx: YearContext) -> list[DecisionSlot]:
    blue = _blue_candidates(ctx)
    out = []
    for pid, bids in sorted(_person_bids(ctx).items()):
        if pid not in blue:
            continue
        for bid in bids:
            if _simplified_books(ctx, pid, bid):
                continue  # 簡易帳簿・現金式は正規の簿記でない（判断は要らない）
            out.append(
                DecisionSlot(
                    key=f"{pid}:{bid}",
                    target={"person": pid, "business_id": bid, "tax_year": ctx.year},
                    matches=lambda rec, pid=pid, bid=bid: rec["subject"]["person"] == pid and rec["subject"]["business_id"] == bid,
                )
            )
    return out


PLAN_CANDIDATES = (
    Candidate({"method": "e_tax", "within_deadline": True, "statements_attached": True}, "期限内・e-Tax・書類の添付あり"),
    Candidate({"method": "paper", "within_deadline": True, "statements_attached": True}, "期限内・書面・書類の添付あり"),
    Candidate({"method": "paper", "within_deadline": False, "statements_attached": True}, "期限後"),
)


def _plan_people(ctx: YearContext) -> list[str]:
    blue = _blue_candidates(ctx)
    bids = _person_bids(ctx)
    return sorted(p for p in ctx.persons if p in blue and (p in bids or _has_rental(ctx, p)))


def _plan_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    for pid in _plan_people(ctx):
        out.append(
            DecisionSlot(
                key=pid,
                target={"person": pid, "tax_year": ctx.year},
                matches=lambda rec, pid=pid: rec["subject"]["person"] == pid,
                candidates=PLAN_CANDIDATES,
            )
        )
    return out


def _family_pairs(ctx: YearContext) -> list[tuple[str, str]]:
    """生計を一にするかの判定が要る（支払う人, 受け取る親族）の組。"""
    family = {p["id"] for p in ctx.ir["persons"]}
    owners = _owner(ctx)
    out: list[tuple[str, str]] = []
    for kind, role, other in (("business_expense", "payer", "payee"), ("payroll_paid", "employer", "recipient")):
        for r in ctx.records(kind):
            if _on_year(r) != ctx.year:
                continue
            o = r["roles"].get(other)
            if o in family and r["roles"][role] in ctx.persons:
                out.append((r["roles"][role], o))
    for r in ctx.records("business_engagement"):
        if overlaps_year(r.get("when"), ctx.year) and owners.get(r["attributes"]["business_id"]) == r["roles"]["business_owner"]:
            out.append((r["roles"]["business_owner"], r["roles"]["relative"]))
    for r in ctx.records("salary_payment"):  # 家族の業務から受けた給与（所法56 の受取側）
        p = r["roles"].get("payer")
        if p in ctx.persons and p != r["roles"]["recipient"] and _date(r["attributes"]["due_on"]).year == ctx.year:
            out.append((p, r["roles"]["recipient"]))
    return out


def _family_slots(ctx: YearContext) -> list[DecisionSlot]:
    return seikei_slots(ctx, [(a, b) for a, b in _family_pairs(ctx) if a in ctx.persons])


def _reasonable_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.専従者給与の相当性：入力があるときだけ読む（額の判断は候補にならない）。"""
    out = []
    for j in ctx.judgments(K_REASONABLE):
        if not overlaps_year(j.get("when"), ctx.year):
            continue
        e, r = j["subject"]["employer"], j["subject"]["employee"]
        if e in ctx.persons:
            out.append(
                DecisionSlot(
                    key=f"{e}:{r}",
                    target={"employer": e, "employee": r, "tax_year": ctx.year},
                    matches=lambda rec, e=e, r=r: rec["subject"]["employer"] == e and rec["subject"]["employee"] == r,
                    persons=(e,),
                )
            )
    return out


def _cost_for(p: CtPlan, a: Mapping[str, Any], bid: str, ctx_year: int) -> CostInfo:
    amts = a["amounts"]
    cost = amts["acquisition_cost"]
    if not p.fixed_exclusive.get(bid, False):
        return CostInfo(cost, 0)
    ex = amts.get("cost_excluding_consumption_tax")
    tax = amts.get("acquisition_consumption_tax")
    if ex is None and tax is not None:
        ex = cost - tax
    if ex is None:
        return CostInfo(None, 0, "税抜経理の資産に、税抜の取得価額（cost_excluding_consumption_tax か acquisition_consumption_tax）の記録がない")
    prepaid = cost - ex if placed_year(a) == ctx_year else 0
    return CostInfo(ex, prepaid)


def _share_for_asset(rid: str, shares: list[tuple[Mapping[str, Any], Any]]) -> tuple[Fraction | None, tuple[str, ...], set[State]]:
    hits = [(sk, d) for sk, d in shares if sk["purpose"] == "asset_business_share" and rid in sk["record_ids"]]
    if not hits:
        # 家族の使用の割合だけがある：業務の部分は 1−割合（語彙の約束。重複は _family_use_check が入力の誤りにする）
        fam = [(sk, d) for sk, d in shares if sk["purpose"] == "family_use_share" and rid in sk["record_ids"]]
        if len(fam) != 1:
            return None, (), set()
        _, d = fam[0]
        ratio = d.value["ratio"]
        return 1 - Fraction(ratio["num"], ratio["den"]), tuple(d.record_ids), set(d.states)
    if len(hits) > 1:
        return None, (), set()  # 同じ資産に複数の割合：呼び出し側で扱わない（ここでは割合なしにしない）
    _, d = hits[0]
    ratio = d.value["ratio"]
    return Fraction(ratio["num"], ratio["den"]), tuple(d.record_ids), set(d.states)


def _parse_share_key(key: str) -> dict[str, Any]:
    person, purpose, bid, ids = key.split(":", 3)
    return {"person": person, "purpose": purpose, "business_id": bid, "record_ids": [x for x in ids.split(",") if x]}


def _expense_amount(
    ctx: YearContext,
    r: Mapping[str, Any],
    related: Mapping[str, Any],
    shares: list[tuple[Mapping[str, Any], Any]],
    problems: list[tuple[str, tuple[str, ...], tuple[str, ...]]],
    both: tuple[str, ...],
) -> int | None:
    """支出1件のうち必要経費に数える額（判断.業務関連性・判断.按分の割合を当てる）。対象外なら None（problems に足す）。"""
    amount = r["amounts"]["amount"]
    rd = related.get(r["id"])
    if rd is not None and rd.value is False:
        return 0
    hits = [(sk, d) for sk, d in shares if sk["purpose"] == "household_expense_business_share" and r["id"] in sk["record_ids"]]
    if len(hits) > 1:
        problems.append(("同じ支出に家事関連費の按分の判断が複数ある", (r["id"],), both))
        return None
    family = False
    if not hits:
        # 家族の使用の割合だけがある：業務の部分は 1−割合（語彙の約束）。家事関連費と同じく所令96 の区分を要する
        hits = [(sk, d) for sk, d in shares if sk["purpose"] == "family_use_share" and r["id"] in sk["record_ids"]]
        if len(hits) != 1:
            return amount  # なし、又は重複（重複は _family_use_check が入力の誤りにする）
        family = True
    _, d = hits[0]
    value = d.value
    sep = value.get("clearly_separable")
    if sep is None:
        problems.append(("家事関連費・家族の使用の按分の判断に、業務の部分を明らかに区分できるか（clearly_separable）がない（所令96）", (r["id"], *d.record_ids), both))
        return None
    if not sep:
        return 0  # 所令96：明らかに区分できなければ必要経費に算入しない
    ratio = Fraction(value["ratio"]["num"], value["ratio"]["den"])
    return _round_expense(ctx, amount * (1 - ratio if family else ratio))


def _round_expense(ctx: YearContext, value: Fraction) -> int:
    """必要経費の1円未満（按分の結果など）：根拠のない端数の候補（D22 S3）。整数ならそのまま。"""
    if value.denominator == 1:
        return int(value)
    return ctx.round_unfounded(ROUNDING_EXPENSE, value)


@dataclass
class _Sides:
    """1人の、所得の側ごとの集計。"""

    rev: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SIDES, 0))
    exp: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SIDES, 0))
    dep: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SIDES, 0))
    salary: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SIDES, 0))
    deduction: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SIDES, 0))
    ids: dict[str, set[str]] = field(default_factory=lambda: {s: set() for s in SIDES})
    st: dict[str, set[State]] = field(default_factory=lambda: {s: set() for s in SIDES})
    problems: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = field(default_factory=list)  # (理由, 記録, 変数)
    missing: list[tuple[Split, tuple[str, ...]]] = field(default_factory=list)  # (決まらない1か所, 未確定にする変数)
    family_rent: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)  # 家族から受け取った賃料 (支払った人, rent_flow)
    # 所法56 の対価（支払側の記録）：(受け取る親族, 所得の側, 業務の ID, 記録, 事業か〔False は業務で読みが分かれる〕)
    transfers: list[tuple[str, str, str, Mapping[str, Any], bool]] = field(default_factory=list)
    # 不動産所得の物件ごとの必要経費・減価償却費（business_expense・depreciable_asset の property_id。物件のないものは None）
    prop_exp: dict[str | None, int] = field(default_factory=dict)
    prop_dep: dict[str | None, int] = field(default_factory=dict)
    casualty_loss: dict[str, int] = field(default_factory=dict)  # 業務用の土地等の災害等の損失（所法51①④）
    rec_exp: dict[str, int] = field(default_factory=dict)  # 支出の記録 → 必要経費に入れた額（所法56 の受取側の売上の必要経費を移すため）
    # 減価償却資産 → (その年分の償却費〔dep の内訳〕, その資産の仮払消費税等〔exp に入る〕)。所法56 の受取側の売上の必要経費を移すため
    # （depreciable_asset の receipt_id。2026-11-12）
    asset_dep: dict[str, tuple[int, int]] = field(default_factory=dict)
    # 総収入金額・必要経費の内訳（breakdown.py。様式の科目：design-output UO19。2026-11-12）。exp・rev を足す箇所で同じ額を足す
    brk: Breakdown = field(default_factory=Breakdown)
    # 棚卸資産（inventory.py。IK-108）：所得の側 → (期首棚卸高, 期末棚卸高)
    inv: dict[str, tuple[int, int]] = field(default_factory=dict)
    # 業務に係る雑所得の報酬の源泉徴収税額（IK-111）
    misc_withhold: int = 0
    misc_withhold_ids: list[str] = field(default_factory=list)
    misc_withhold_missing: list[str] = field(default_factory=list)
    # 減価償却費の根拠（割増・特別償却の外部の値：special_dep.py。IK-112。2026-11-12）：所得の側 → 根拠
    dep_basis: dict[str, list[BasisEntry]] = field(default_factory=dict)


#: 所得の側 → その入力変数（売上・必要経費・減価償却費）。
SIDE_VARS = {
    "biz": (V_BIZ_REV, V_BIZ_EXP, V_BIZ_DEP),
    "misc": (V_MISC_REV, V_MISC_EXP, V_MISC_DEP),
    "rental": (V_RENT_REV, V_RENT_EXP, V_RENT_DEP),
}
ALL_BUSINESS_VARS = tuple(v for t in SIDE_VARS.values() for v in t) + (V_BIZ_SALARY, V_RENT_SALARY, V_BIZ_FAM_DED, V_RENT_FAM_DED)


def _rental_flows(ctx: YearContext, pid: str, family: set[str], sides: _Sides) -> None:
    """不動産所得の総収入金額（rent_flow）。敷金の預りと返還は収入にしない。"""
    income_flows = ("rent", "common_service_fee", "key_money", "renewal_fee", "other")
    for r in sorted(ctx.records("rent_flow"), key=lambda r: r["id"]):
        if r["roles"]["recipient"] != pid or _year_of(r) != ctx.year:
            continue
        sides.ids["rental"].add(r["id"])
        sides.st["rental"] |= _states([r])
        ft = r["attributes"]["flow_type"]
        if ft in ("deposit_received", "deposit_returned"):
            continue
        if ft not in income_flows:
            sides.problems.append(("賃料の種類が扱えない", (r["id"],), (V_RENT_REV,)))
            continue
        payer = r["roles"].get("payer")
        if payer in family and payer != pid:
            # 家族からの賃料：いったん数え、支払った人の事業からの対価（所法56）なら _apply_56 が「ないものとみなす」。
            # 家族の家事のための賃料（事業から対価でない）は通常の不動産所得（所法56 は事業から対価の支払を受ける場合だけ）
            sides.family_rent.append((payer, r))
        sides.rev["rental"] += r["amounts"]["amount"]
        sides.brk.add_rev("rental", RENT_FLOW_KEYS.get(ft, "other"), r["amounts"]["amount"])
    for r in ctx.records("rental_property"):
        if r["roles"]["owner"] != pid or not overlaps_year(r.get("when"), ctx.year):
            continue
        share = r["attributes"].get("owner_share")
        if share is not None and Fraction(share["num"], share["den"]) != 1:
            # 共有の賃貸物件：持分による所得の帰属の一次情報が docs にない（fudosan §9-8）。記録の額をそのまま数えた値（記録が持分の額）と
            # 持分を掛けた値（記録が全体の額）で分かれるので、不動産所得の側を未確定にする（D22 S1）
            sides.missing.append((undetermined(
                f"一次情報:共有の賃貸物件の所得の帰属:{r['id']}", Means.PRIMARY_SOURCE,
                {"person": pid, "property_id": r["id"], "事項": "共有の賃貸物件の収入・必要経費の持分による帰属（fudosan §9-8。記録の額が持分の額か全体の額かの約束も要る）"},
                ("記録の額が持分の額", "記録の額に持分を掛ける"),
            ), tuple(SIDE_VARS["rental"])))


def _land_interest(ctx: YearContext, pid: str, interest_recs: list[Mapping[str, Any]]) -> tuple[int | None, tuple[str, ...]]:
    """土地等を取得するために要した負債の利子の額。土地の借入れだけなら借入金の利子の全部。土地と建物の借入れが混ざるなら決められない（None）。"""
    props = {r["id"]: r for r in ctx.records("rental_property")}
    loans = [r for r in ctx.records("loan") if r["roles"]["borrower"] == pid and overlaps_year(r.get("when"), ctx.year)]
    ids = tuple(r["id"] for r in loans)
    land = [r for r in loans if props.get(r["attributes"].get("purpose_asset_id", ""), {}).get("attributes", {}).get("property_type") in LAND_PROPERTY_TYPES]
    if not land:
        return 0, ids
    if len(land) == len(loans):
        return sum(r["amounts"]["amount"] for r in interest_recs), ids
    return None, ids


def _all_villa(ctx: YearContext, pid: str) -> tuple[bool | None, tuple[str, ...]]:
    props = [r for r in ctx.records("rental_property") if r["roles"]["owner"] == pid and overlaps_year(r.get("when"), ctx.year)]
    if not props:
        return False, ()
    # 別荘等か：判断.不動産の区分の材料 の villa_purpose があればそれ、なければ held_as_villa（IK-118）
    marked = [(_rc.villa_flag(ctx, r), r["id"]) for r in props]
    ids = tuple(sorted({rid for _, rid in marked} | {j for (_, js), _ in marked for j in js}))
    flags = {f for (f, _), _ in marked}
    if len(flags) > 1:
        return None, ids
    return flags.pop(), ids


def _land_interest_by_loan(ctx: YearContext, interest_recs: list[Mapping[str, Any]]) -> int | None:
    """利子の支出が全部借入れを指していれば（business_expense.attributes.loan_id）、目的の資産が土地等の借入れの利子の合計。指していなければ None。"""
    if not interest_recs or any(not r["attributes"].get("loan_id") for r in interest_recs):
        return None
    props = {r["id"]: r for r in ctx.records("rental_property")}
    loans = {r["id"]: r for r in ctx.records("loan")}
    total = 0
    for r in interest_recs:
        loan = loans.get(r["attributes"]["loan_id"], {})
        ptype = props.get(loan.get("attributes", {}).get("purpose_asset_id", ""), {}).get("attributes", {}).get("property_type")
        if ptype in LAND_PROPERTY_TYPES:
            total += r["amounts"]["amount"]
    return total


RENT_INCOME_FLOWS = ("rent", "common_service_fee", "key_money", "renewal_fee", "other")


def _arrangement_land_interest(
    ctx: YearContext, pid: str, interest_recs: list[Mapping[str, Any]], sp_deemed: rsp.Deemed
) -> tuple[int, list[str]]:
    """措通41の4−4：組合事業・信託の区分ごとの土地等の負債の利子のうち、生じなかったものとみなされる金額に達するまでの額の合計（土地等の負債の
    利子から差し引く額）と、組合事業等の物件か決められない利子の支出の記録。利子の支出は借入れ（loan_id の目的の資産）か物件（property_id）で結ぶ。"""
    props = {r["id"]: r for r in ctx.records("rental_property") if r["roles"]["owner"] == pid}
    loans = {r["id"]: r for r in ctx.records("loan")}

    def group(prop: Mapping[str, Any]) -> str | None:
        a = prop.get("attributes", {})
        return f"{'trust' if a.get('held_through') == 'trust' else 'partnership'}:{a['arrangement_id']}" if a.get("held_through") and a.get("arrangement_id") else None

    by_arr: dict[str, int] = {}
    unlinked: list[str] = []
    for r in interest_recs:
        loan = loans.get(r["attributes"].get("loan_id") or "")
        target = props.get(loan["attributes"].get("purpose_asset_id", "")) if loan else props.get(r["attributes"].get("property_id") or "")
        if target is None:
            unlinked.append(r["id"])
            continue
        g = group(target)
        if g is not None and target["attributes"].get("property_type") in LAND_PROPERTY_TYPES:
            by_arr[g] = by_arr.get(g, 0) + r["amounts"]["amount"]
    return rsp.land_interest_after_arrangements(by_arr, sp_deemed.by_arrangement), sorted(unlinked)


def _villa_by_property(ctx: YearContext, pid: str, s: _Sides) -> tuple[int, int] | None:
    """物件ごとの収支（property_id）から（別荘等の物件の収支の合計, それ以外の合計）。物件に結びつかない収入・支出があれば None。"""
    if s.salary["rental"] or s.deduction["rental"]:
        return None
    if sum(v for k, v in s.prop_exp.items() if k) != s.exp["rental"] or sum(v for k, v in s.prop_dep.items() if k) != s.dep["rental"]:
        return None
    leases = {r["id"]: r for r in ctx.records("lease")}
    props = {r["id"]: r for r in ctx.records("rental_property") if r["roles"]["owner"] == pid and overlaps_year(r.get("when"), ctx.year)}
    rev: dict[str, int] = {}
    for r in ctx.records("rent_flow"):
        if r["roles"]["recipient"] != pid or _year_of(r) != ctx.year or r["attributes"]["flow_type"] not in RENT_INCOME_FLOWS:
            continue
        pk = r["attributes"].get("property_id") or leases.get(r["attributes"].get("lease_id", ""), {}).get("attributes", {}).get("property_id")
        if pk not in props:
            return None
        rev[pk] = rev.get(pk, 0) + r["amounts"]["amount"]
    if sum(rev.values()) != s.rev["rental"]:
        return None  # 所法56 で除いた賃料・資産の売却代金などがあり、物件ごとに合わない
    keys = set(rev) | {k for k in s.prop_exp if k} | {k for k in s.prop_dep if k}
    if keys - set(props):
        return None
    villa = {k for k, r in props.items() if _rc.villa_flag(ctx, r)[0]}
    net = {k: rev.get(k, 0) - s.prop_exp.get(k, 0) - s.prop_dep.get(k, 0) for k in keys}
    return sum(v for k, v in net.items() if k in villa), sum(v for k, v in net.items() if k not in villa)


def _year_end_or_death(ctx: YearContext, pid: str) -> _dt.date:
    end = _dt.date(ctx.year, 12, 31)
    death = ctx.death_on(pid)
    return min(end, death) if death else end


def _reading_56(payer: str, payee: str, rid: str) -> Split:
    """業務からの生計を一にする親族への対価：所法56 を当てる（条文は事業）か当てない（TA2210 は業務）かの分かれ目（D22 S1：支えが同程度）。"""
    return undetermined(
        f"一次情報:所法56の業務への当てはめ:{rid}",
        Means.PRIMARY_SOURCE,
        {
            "payer": payer,
            "payee": payee,
            "record_id": rid,
            "事項": "業務（雑所得・事業的規模でない不動産所得）から生計を一にする親族への対価に所得税法第56条が及ぶか（条文は「事業」、TA2210 は「業務」）",
        },
        ("所法56を当てる（支払側の必要経費にせず、受取側はないものとみなす）", "所法56を当てない"),
    )


def _fact_56(sid: str, target: Mapping[str, Any], what: str) -> Split:
    return undetermined(sid, Means.FACT, {**target, "入力": what}, ("所法56の対価に当たる", "当たらない"))


def _missing_for(s: _Sides, variable: str) -> tuple[Split, ...]:
    return tuple(sp for sp, vs in s.missing if variable in vs)


LINK_56_REASON = (
    "入力の矛盾：家族への支払（business_expense の rent_flow_id・receipt_id、payroll_paid の receipt_id）が指す受け取った側の記録が、"
    "その家族のその年分の記録でないか、額が合わない"
)
LINK_56_SIDE_REASON = (
    "入力の矛盾：家族から受けた対価の売上（business_receipt）を receipt_id で指す受け取った側の支出・減価償却資産が、その売上と違う所得の種類の業務のものか、"
    "同じ売上を所得の種類の違う支払側の記録が指す（receipt_id・business_id を直せば決まる）"
)


def _apply_56(ctx: YearContext, sides: Mapping[str, _Sides], side_ofs: Mapping[str, Mapping[str, str]] | None = None) -> None:
    """所法56 の受取側（全員の集計の後）。支払側の対価（_Sides.transfers）と受取側の記録を結びつける。

    - 受取側の賃料（rent_flow の payer が支払った人）：支払った人の業務の支出（business_expense）が rent_flow_id で指す賃料（2026-11-12 の語彙）、
      指していなければ支払った人の支出と受取側の賃料の合計が一致するときにその業務からの対価と読む（一致しなければ c-入力：rent_flow_id を書けば決まる）。
      事業からの対価なら総収入金額から除き、受取側の不動産所得の必要経費（減価償却費を含む）のうちその物件の分を支払側の事業の必要経費に移す。
      業務からの対価なら数えたまま、業務への当てはめの分かれ目（一次情報）を付ける。
    - 支払った人の支出・報酬（payroll_paid の professional_fee）が受取側の売上（business_receipt）を receipt_id で指していれば、事業からの対価はその売上を除き、
      受取側のその業務の必要経費を支払側に移す（受取側の所得の側がその業務だけで、売上が全部その対価のとき。ほかは分かれ目）。
      指していなければ、売上に対価が含まれるかを決められないので受取側の売上を未確定にする（c-入力）。
    - 受取側の給与（salary_payment の役割 payer）は _family_salary_received（kyuyo が段で読む）。
    """
    side_ofs = side_ofs or {}
    for p in sorted(sides):
        sp = sides[p]
        by_q: dict[str, list[tuple[str, str, str, Mapping[str, Any], bool]]] = {}
        for t in sp.transfers:
            by_q.setdefault(t[0], []).append(t)
        for q, items in sorted(by_q.items()):
            sq = sides.get(q)
            if sq is None:
                continue
            ids = [t[3]["id"] for t in items]
            target = {"payer": p, "payee": q, "record_ids": ids}
            flows = [r for payer, r in sq.family_rent if payer == p]
            flow_by_id = {r["id"]: r for r in flows}
            exp_items = [t for t in items if t[3]["kind"] == "business_expense" and not t[3]["attributes"].get("receipt_id")]
            covered: list[tuple[str, str, str, Mapping[str, Any], bool]] = []
            linked = [t for t in exp_items if t[3]["attributes"].get("rent_flow_id")]
            if linked and len(linked) == len(exp_items):
                used = {t[3]["attributes"]["rent_flow_id"] for t in linked}
                lflows = [flow_by_id[i] for i in sorted(used) if i in flow_by_id]
                if len(lflows) != len(used) or sum(r["amounts"]["amount"] for r in lflows) != sum(t[3]["amounts"]["amount"] for t in linked):
                    rids = tuple(sorted({*ids, *used}))
                    sq.problems.append((LINK_56_REASON, rids, tuple(SIDE_VARS["rental"])))
                    for t in linked:
                        sp.problems.append((LINK_56_REASON, rids, tuple(SIDE_VARS[t[1]])))
                    covered = exp_items
                flows = lflows
            rent_ids = [r["id"] for r in flows]
            if flows and exp_items and not covered:
                shared = {rid for j in ctx.judgments(K_SHARE) if j["value"]["purpose"] == "household_expense_business_share" for rid in j["subject"].get("record_ids", [])}
                total_rent = sum(r["amounts"]["amount"] for r in flows)
                total_exp = sum(t[3]["amounts"]["amount"] for t in exp_items)
                kinds = {t[4] for t in exp_items}
                if total_rent != total_exp or len(kinds) != 1:
                    sp_ = _fact_56(
                        f"事実:所法56の賃料の結びつき:{p}:{q}:{ctx.year}",
                        {**target, "rent_flow_ids": rent_ids},
                        "家族からの賃料（rent_flow）のうち、支払った人の事業・業務から支払われた分（business_expense.attributes.rent_flow_id を書けば決まる）",
                    )
                    sq.missing.append((sp_, tuple(SIDE_VARS["rental"])))
                    for t in exp_items:
                        sp.missing.append((sp_, tuple(SIDE_VARS[t[1]])))
                    covered = exp_items
                elif any(t[3]["id"] in shared for t in exp_items):
                    # 家事関連費の按分の判断がある賃料：事業の部分だけが「事業から対価」で、家事の部分は通常の不動産所得になるかの一次情報がない
                    sp_ = undetermined(
                        f"一次情報:家事と兼用の家族への賃料の所法56:{p}:{q}:{ctx.year}",
                        Means.PRIMARY_SOURCE,
                        {**target, "rent_flow_ids": rent_ids, "事項": "家事関連費の按分がある生計を一にする親族への賃料のうち、所法56 で受取側がないものとみなす部分（事業の部分だけか全部か）"},
                        ("事業の部分だけ", "全部"),
                    )
                    sq.missing.append((sp_, tuple(SIDE_VARS["rental"])))
                    for t in exp_items:
                        sp.missing.append((sp_, tuple(SIDE_VARS[t[1]])))
                    covered = exp_items
                elif kinds == {False}:
                    for t in exp_items:
                        sq.missing.append((_reading_56(p, q, t[3]["id"]), tuple(SIDE_VARS["rental"])))
                    covered = exp_items
                else:
                    covered = exp_items
                    sq.rev["rental"] -= total_rent
                    for f_ in flows:  # 内訳（breakdown.py）も同じ賃料の種類から引く
                        sq.brk.add_rev("rental", RENT_FLOW_KEYS.get(f_["attributes"]["flow_type"], "other"), -f_["amounts"]["amount"])
                    sq.ids["rental"] |= set(ids)
                    sp.ids[exp_items[0][1]] |= set(rent_ids)
                    _move_expenses_56(ctx, p, q, sp, sq, exp_items, flows)
            # 対価のうち賃料と結びつかなかったもの（給与〔wages〕は受取側の給与所得で _family_salary_received が扱う）
            rest = [t for t in items if t not in covered and not (t[3]["kind"] == "payroll_paid" and t[3]["attributes"]["pay_type"] != "professional_fee")]
            receipts = {r["id"]: r for r in ctx.records("business_receipt") if r["roles"]["recipient"] == q and _on_year(r) == ctx.year}
            linked_r = [t for t in rest if t[3]["attributes"].get("receipt_id")]
            if linked_r:
                rest = [t for t in rest if t not in linked_r]
                _receipts_56(ctx, p, q, sp, sq, linked_r, receipts, side_ofs.get(q, {}))
            if rest and receipts:
                sp_ = _fact_56(
                    f"事実:所法56の売上の結びつき:{p}:{q}:{ctx.year}",
                    {**target, "receipt_ids": sorted(receipts)},
                    "親族の業務の売上（business_receipt）に、支払った人の業務からの対価が含まれるか（支払った人の記録の attributes.receipt_id を書けば決まる）",
                )
                for side in ("biz", "misc"):
                    sq.missing.append((sp_, tuple(SIDE_VARS[side])))


def _receipts_56(
    ctx: YearContext,
    p: str,
    q: str,
    sp: _Sides,
    sq: _Sides,
    linked: list[tuple[str, str, str, Mapping[str, Any], bool]],
    receipts: Mapping[str, Mapping[str, Any]],
    q_side_of: Mapping[str, str],
) -> None:
    """支払った人（p）の支出・報酬が receipt_id で指す受取側（q）の売上（所法56）。"""
    moved: dict[str, list[tuple[str, str, str, Mapping[str, Any], bool]]] = {}
    for t in linked:
        rec = receipts.get(t[3]["attributes"]["receipt_id"])
        q_side = q_side_of.get(rec["attributes"]["business_id"]) if rec is not None else None
        if rec is None or q_side is None or rec["amounts"]["amount"] != t[3]["amounts"]["amount"]:
            rids = (t[3]["id"], t[3]["attributes"]["receipt_id"])
            sq.problems.append((LINK_56_REASON, rids, tuple(v for side in ("biz", "misc") for v in SIDE_VARS[side])))
            sp.problems.append((LINK_56_REASON, rids, tuple(SIDE_VARS[t[1]])))
            continue
        if not t[4]:
            sq.missing.append((_reading_56(p, q, t[3]["id"]), tuple(SIDE_VARS[q_side])))
            continue
        sq.rev[q_side] -= rec["amounts"]["amount"]
        sq.brk.add_rev(q_side, REV_SALES, -rec["amounts"]["amount"])
        sq.ids[q_side] |= {t[3]["id"], rec["id"]}
        sp.ids[t[1]].add(rec["id"])
        moved.setdefault(q_side, []).append(t)
    for q_side, ts in sorted(moved.items()):
        # 受取側のその対価に係る必要経費（所法56 後段）：受取側のその所得の側の業務が1つで、その年の売上が全部その対価なら、その側の必要経費の全部
        bids = [b for b, side in q_side_of.items() if side == q_side]
        used = {t[3]["attributes"]["receipt_id"] for t in ts}
        others = [r for r in receipts.values() if q_side_of.get(r["attributes"]["business_id"]) == q_side and r["id"] not in used]
        targets = {t[1] for t in ts}
        if len(bids) == 1 and not others and len(targets) == 1 and not sq.salary[q_side] and not sq.deduction[q_side]:
            side = next(iter(targets))
            sp.exp[side] += sq.exp[q_side]
            sq.brk.move_all_to(q_side, sp.brk, side)
            sp.dep[side] += sq.dep[q_side]
            sp.ids[side] |= sq.ids[q_side]
            sp.st[side] |= sq.st[q_side]
            sq.exp[q_side] = 0
            sq.dep[q_side] = 0
            continue
        # 受取側の支出・減価償却資産がその売上を receipt_id で指していれば（business_expense・depreciable_asset の receipt_id：その売上のための支出・
        # その売上に専ら用いた資産。2026-11-12 の語彙）、その支出の額・資産の償却費を、その売上を指す支払側の記録の所得の側へ移す。
        # 指していない支出・資産は移さない（その対価に係る必要経費でない読み：business_expense の receipt_id と同じ。IK-32）
        side_of_receipt: dict[str, set[str]] = {}
        for t in ts:
            side_of_receipt.setdefault(t[3]["attributes"]["receipt_id"], set()).add(t[1])
        ambiguous = sorted(r for r, sides in side_of_receipt.items() if len(sides) > 1)
        if ambiguous:
            # 同じ売上を、所得の側の違う支払側の記録が指す（どちらの側の必要経費に移すか決まらない：記録の矛盾）
            rids = tuple(sorted({t[3]["id"] for t in ts if t[3]["attributes"]["receipt_id"] in ambiguous} | set(ambiguous)))
            sq.problems.append((LINK_56_SIDE_REASON, rids, tuple(SIDE_VARS[q_side])))
            for side in targets:
                sp.problems.append((LINK_56_SIDE_REASON, rids, tuple(SIDE_VARS[side])))
            continue
        exps = [
            r for r in ctx.records("business_expense")
            if r["roles"]["payer"] == q and r["attributes"].get("receipt_id") in used and r["id"] in sq.rec_exp
        ]
        assets = [
            a for a in ctx.records("depreciable_asset")
            if a["roles"]["owner"] == q and a["attributes"].get("receipt_id") in used and a["id"] in sq.asset_dep
        ]
        elsewhere = sorted(r["id"] for r in [*exps, *assets] if q_side_of.get(r["attributes"].get("business_id", "")) != q_side)
        if elsewhere:
            # 売上と違う所得の側の業務の支出・資産がその売上を指す（記録の矛盾：receipt_id か business_id を直せば決まる）
            sq.problems.append((LINK_56_SIDE_REASON, tuple(elsewhere), tuple(v for vs in SIDE_VARS.values() for v in vs)))
            for side in targets:
                sp.problems.append((LINK_56_SIDE_REASON, tuple(elsewhere), tuple(SIDE_VARS[side])))
            continue
        for r in exps:
            side = next(iter(side_of_receipt[r["attributes"]["receipt_id"]]))
            amount = sq.rec_exp[r["id"]]
            sp.exp[side] += amount
            sq.exp[q_side] -= amount
            sq.brk.move_records_to(q_side, sp.brk, side, sq.rec_exp, (r["id"],))
            sp.ids[side].add(r["id"])
        for a in assets:
            side = next(iter(side_of_receipt[a["attributes"]["receipt_id"]]))
            dep, prepaid = sq.asset_dep[a["id"]]
            sp.dep[side] += dep
            sq.dep[q_side] -= dep
            sp.exp[side] += prepaid
            sq.exp[q_side] -= prepaid
            sq.brk.move_to(q_side, sp.brk, side, "consumption_tax", prepaid)  # 資産の仮払消費税等（内訳は消費税等）
            sp.ids[side].add(a["id"])


def _move_expenses_56(
    ctx: YearContext,
    p: str,
    q: str,
    sp: _Sides,
    sq: _Sides,
    items: list[tuple[str, str, str, Mapping[str, Any], bool]],
    flows: list[Mapping[str, Any]],
) -> None:
    """受取側（q）の不動産所得の必要経費・減価償却費のうち、その対価の物件の分を支払側（p）の事業の必要経費に移す（所法56 後段）。

    受取側の貸付けがその対価だけ（ほかの賃料がなく、持っている賃貸物件が全部その対価の物件）なら全部を移す。そうでなければ、受取側の不動産所得の
    支出・減価償却資産が全部物件に結びついている（business_expense・depreciable_asset の property_id。2026-11-12 の語彙）ときに、その物件の分だけを移す。
    どちらでもなければ両方を未確定にする（c-入力：property_id を書けば決まる）。
    """
    leases = {r["id"]: r for r in ctx.records("lease")}
    props_used = {r["attributes"].get("property_id") or leases.get(r["attributes"].get("lease_id", ""), {}).get("attributes", {}).get("property_id") for r in flows}
    props = {r["id"] for r in ctx.records("rental_property") if r["roles"]["owner"] == q and overlaps_year(r.get("when"), ctx.year)}
    if None in props_used:  # 物件の記載のない賃料は、物件が1つならその物件
        props_used = (props_used - {None}) | (props if len(props) == 1 else {None})
    other_rent = sq.rev["rental"] != 0 or any(payer != p for payer, _ in sq.family_rent)
    targets = {t[1] for t in items}
    side = next(iter(targets)) if len(targets) == 1 else None
    if side is not None and None not in props_used and not sq.salary["rental"] and not sq.deduction["rental"]:
        move_exp: int | None
        move_dep: int | None
        if not other_rent and not (props - props_used):
            move_exp, move_dep = sq.exp["rental"], sq.dep["rental"]
        elif sum(v for k, v in sq.prop_exp.items() if k) == sq.exp["rental"] and sum(v for k, v in sq.prop_dep.items() if k) == sq.dep["rental"]:
            move_exp = sum(sq.prop_exp.get(k, 0) for k in props_used)
            move_dep = sum(sq.prop_dep.get(k, 0) for k in props_used)
        else:
            move_exp = move_dep = None
        if move_exp is not None and move_dep is not None:
            sp.exp[side] += move_exp
            sp.dep[side] += move_dep
            sp.ids[side] |= sq.ids["rental"]
            sp.st[side] |= sq.st["rental"]
            if move_exp == sq.exp["rental"]:  # 内訳（breakdown.py）：全部か、物件の支出の記録の分
                sq.brk.move_all_to("rental", sp.brk, side)
            else:
                moved_ids = [
                    r["id"] for r in ctx.records("business_expense")
                    if r["roles"]["payer"] == q and r["attributes"].get("property_id") in props_used and r["id"] in sq.rec_exp
                ]  # fmt: skip
                sq.brk.move_records_to("rental", sp.brk, side, sq.rec_exp, moved_ids)
            sq.exp["rental"] -= move_exp
            sq.dep["rental"] -= move_dep
            for k in props_used:
                sq.prop_exp.pop(k, None)
                sq.prop_dep.pop(k, None)
            return
    sp_ = _fact_56(
        f"事実:所法56の受取側の必要経費:{p}:{q}:{ctx.year}",
        {"payer": p, "payee": q, "rent_flow_ids": [r["id"] for r in flows]},
        "受取側の不動産所得の必要経費のうち、その対価に係る部分（受取側の business_expense・depreciable_asset の property_id、賃料の property_id か lease_id を書けば決まる）",
    )
    sq.missing.append((sp_, tuple(SIDE_VARS["rental"])))
    sp.missing.append((sp_, tuple(SIDE_VARS[side]) if side is not None else tuple(v for t in SIDE_VARS.values() for v in t)))


def _business(ctx: YearContext, out: ModuleInputs) -> None:
    owners = _owner(ctx)
    act = _activity(ctx)
    family = {p["id"] for p in ctx.ir["persons"]}
    rentals = _rental_bids(ctx)
    bids_of = _person_bids(ctx)
    assets_by: dict[str, list[Mapping[str, Any]]] = {}
    for a in ctx.records("depreciable_asset"):
        if placed_year(a) <= ctx.year:
            assets_by.setdefault(a["roles"]["owner"], []).append(a)
    related = {s.key: ctx.decision(K_RELATED, s.key) for s in _related_slots(ctx)}
    shares = [(_parse_share_key(s.key), ctx.decision(K_SHARE, s.key)) for s in _share_slots(ctx)]
    deemed: dict[str, list[tuple[int, list[str], set[State]]]] = {}
    deemed_from: dict[str, set[str]] = {}  # 専従者 → 事業主（事業専従者控除額が対象外の事業主の分は、みなし給与も対象外にする）
    tainted: dict[str, list[OutOfScopeReason]] = {}  # 事業主 → 事業専従者控除額を対象外にした理由
    staged: list[tuple[Any, ...]] = []
    unsure: dict[str, list[Split]] = {}  # 事業主 → 事業専従者控除額の基礎を未確定にした1か所
    for pid in ctx.persons:
        by_biz = act.get(pid, {})
        s = _Sides()
        both = tuple(v for t in SIDE_VARS.values() for v in t)
        side_of: dict[str, str] = {}
        side_open: dict[str, bool] = {}  # 業務 → 事業と称するに至る程度かが未入力（候補で評価している）か（割増・特別償却の所得の側：special_dep.py）
        for bid in bids_of.get(pid, []):
            if bid in rentals.get(pid, ()):
                side_of[bid] = "rental"
            else:
                d = ctx.decision(K_JIGYO, f"{pid}:{bid}")
                side_of[bid] = "biz" if d.value else "misc"
                side_open[bid] = bool(d.open)
                s.ids[side_of[bid]] |= set(d.record_ids) | {bid}
                s.st[side_of[bid]] |= set(d.states)
        # 前々年分の業務に係る雑所得の収入金額（所法120⑥ の材料。prior_years.py：IK-114）
        _prior.write_prior(ctx, out, pid, any(v == "misc" for v in side_of.values()))
        fam_pay: dict[str, list[Mapping[str, Any]]] = {}
        interest_recs: list[Mapping[str, Any]] = []
        rent_scale: Any = None
        if _has_rental(ctx, pid):
            rent_scale = ctx.decision(K_RENT_SCALE, pid)
            s.ids["rental"] |= set(rent_scale.record_ids)
            s.st["rental"] |= set(rent_scale.states)
        rent_is_business = bool(rent_scale.value) if rent_scale is not None else False
        for bid, recs in sorted(by_biz.items()):
            rec_ids = tuple(r["id"] for r in recs)
            if not bid:
                s.problems.append(("業務の識別子（business_id）のない支出・給与の支払がある（どの業務の必要経費か決まらない）", rec_ids, both))
                continue
            if owners.get(bid) != pid:
                s.problems.append(("ほかの人の業務の売上・支出を受け取り・支払っている", rec_ids, both))
                continue
            side = side_of[bid]
            for r in sorted(recs, key=lambda r: r["id"]):
                s.ids[side].add(r["id"])
                s.st[side] |= _states([r])
                a = r.get("attributes", {})
                if r["kind"] == "business_receipt":
                    if a.get("contract_document") in ("employment_contract", "labor_conditions_notice"):
                        # 雇用契約の書面のある売上：判断.雇用か請負か で決める。雇用なら給与所得（kyuyo の salary_payment で記録する入力の誤り）、
                        # 請負なら業務の売上。未入力なら売上として数え、雇用ならこの売上は給与所得になるので未確定にする（D21 R6）
                        ej = [j for j in ctx.judgments(K_EMPLOY) if j["subject"]["record_id"] == r["id"]]
                        if ej and ej[0]["value"] == "employment":
                            s.problems.append((EMPLOYMENT_RECEIPT_REASON, (r["id"], ej[0]["id"]), both))
                            continue
                        if ej:
                            s.ids[side].add(ej[0]["id"])
                            s.st[side] |= _states(ej[:1])
                        else:
                            s.missing.append((undetermined(
                                f"判断:雇用か請負か:{r['id']}", Means.JUDGMENT,
                                {"person": pid, "record_id": r["id"], "入力": "判断.雇用か請負か（雇用なら給与の支払 salary_payment として記録する）"},
                                ("請負（業務の売上）", "雇用（給与所得）"),
                            ), tuple(SIDE_VARS[side])))
                    s.rev[side] += r["amounts"]["amount"]
                    s.brk.add_rev(side, REV_SALES, r["amounts"]["amount"])
                    continue
                if _is_family_salary(r):
                    fam_pay.setdefault(bid, []).append(r)
                    continue
                other = r["roles"].get("recipient") if r["kind"] == "payroll_paid" else r["roles"].get("payee")
                if other in family and other != pid:
                    sd = ctx.decision(K_SEIKEI, pair_key(pid, other))
                    s.ids[side] |= set(sd.record_ids)
                    s.st[side] |= set(sd.states)
                    if sd.value and is_relative(ctx, pid, other, _year_end_or_death(ctx, pid)):
                        # 所法56：事業（事業所得・事業的規模の不動産所得）から生計を一にする親族への対価は必要経費に算入しない。
                        # 業務（雑所得・事業的規模でない不動産所得）は条文（事業）と TA2210（業務）で読みが分かれる：数えた値に未確定を付ける
                        is_business = side == "biz" or (side == "rental" and rent_is_business)
                        s.transfers.append((other, side, bid, r, is_business))
                        s.ids[side].add(r["id"])
                        if is_business:
                            continue
                        s.missing.append((_reading_56(pid, other, r["id"]), tuple(SIDE_VARS[side])))
                amount = _expense_amount(ctx, r, related, shares, s.problems, both)
                if amount is None:
                    continue
                rd = related.get(r["id"])
                if rd is not None:
                    s.ids[side] |= set(rd.record_ids)
                    s.st[side] |= set(rd.states)
                if side == "rental" and r["kind"] == "business_expense" and a.get("expense_category") in INTEREST_CATEGORIES:
                    interest_recs.append(r)
                s.exp[side] += amount
                s.brk.add_record(side, r, amount)
                if side == "rental":
                    pk = a.get("property_id")
                    s.prop_exp[pk] = s.prop_exp.get(pk, 0) + amount
                s.rec_exp[r["id"]] = amount
        _business_person_checks(ctx, pid, s, both)
        _prior.cash_basis(ctx, pid, s.problems, side_of, SIDE_VARS, s.ids)  # 選択.現金主義（業務に係る雑所得）：IK-64・IK-115
        _business_casualties(ctx, pid, s, both, side_of)
        for sk, d in shares:
            if sk["person"] == pid:
                for side in SIDES:
                    s.ids[side] |= set(d.record_ids)
        # 不動産所得の収入
        if _has_rental(ctx, pid):
            _rental_flows(ctx, pid, family, s)
            # 判断.不動産の区分の材料・選択.不動産所得の計上（rental_choices.py：IK-116〜IK-119）
            _rc.contribute(ctx, pid, s.problems, s.missing, s.ids["rental"], tuple(SIDE_VARS["rental"]))
        # 消費税等の経理方式（課税事業者の記録がある人）
        ct = ct_plan(ctx, pid, bids_of.get(pid, []))
        for text, rids in ct.problems:
            s.problems.append((text, rids, both))
        # 減価償却資産
        res = AssetResult()
        blue_splits: list[Split] = []
        blue_st = lambda y: blue_state(ctx, pid, y, blue_splits)[0] == BLUE_APPROVED  # noqa: E731

        def blue_now() -> tuple[bool, bool]:
            """その年分の青色申告の承認（割増・特別償却の要件：special_dep.py）。読みで分かれれば分かれ目を blue_splits に足し、(承認なし, True)。"""
            n = len(blue_splits)
            approved = blue_st(ctx.year)
            return approved, len(blue_splits) > n

        problems_before, missing_before = len(s.problems), len(s.missing)  # 減価償却費の計算の行（下）の対象外・未確定の材料
        for asset in sorted(assets_by.get(pid, []), key=lambda r: r["id"]):
            bid = asset["attributes"].get("business_id")
            rid = asset["id"]
            if not bid or owners.get(bid) != pid or bid not in side_of:
                s.problems.append(("減価償却資産に業務の識別子がない、又はほかの人の業務", (rid,), both))
                continue
            side = side_of[bid]
            hits = [sk for sk, _ in shares if sk["purpose"] == "asset_business_share" and rid in sk["record_ids"]]
            if len(hits) > 1:
                s.problems.append(("同じ資産に事業専用割合の判断が複数ある", (rid,), both))
                continue
            share, sids, sstates = _share_for_asset(rid, shares)
            biz_rec = next(r for r in ctx.records("business") if r["id"] == bid)
            period = (_date(biz_rec["when"]["from_on"]), _date(biz_rec["when"]["to_on"]) if biz_rec["when"].get("to_on") else None)
            info = _cost_for(ct, asset, bid, ctx.year)
            before = len(res.problems)
            n_splits = len(blue_splits)
            dep_before = res.expense.get(side, 0)
            asset_year(ctx, res, asset, side, info, blue_st, share, sids, sstates, period, blue_now=blue_now, side_open=side_open.get(bid, False))
            if side == "rental":  # 物件ごとの減価償却費（depreciable_asset の property_id）
                pk = asset["attributes"].get("property_id")
                s.prop_dep[pk] = s.prop_dep.get(pk, 0) + res.expense.get(side, 0) - dep_before
            for sp_ in blue_splits[n_splits:]:  # 措法28の2 の青色の承認が読みで分かれる（blue_state）
                s.missing.append((sp_, tuple(SIDE_VARS[side])))
            prepaid_before = res.prepaid_tax.get(side, 0)
            if info.prepaid_tax and len(res.problems) == before:
                res.add_prepaid(side, info.prepaid_tax, (rid,))
            # 資産ごとの償却費（s.dep の内訳）と、その資産の仮払消費税等（s.exp に入る）
            s.asset_dep[rid] = (res.expense.get(side, 0) - dep_before, res.prepaid_tax.get(side, 0) - prepaid_before)
        for text, rids, side in res.problems:
            s.problems.append((text, rids, tuple(SIDE_VARS[side]) if side else both))
        for sp_, side in res.missing:  # 除却の超える部分の所得の種類・措法28の2 の年の上限の選択（assets.py）
            s.missing.append((sp_, tuple(SIDE_VARS[side])))
        # 減価償却費の計算の資産ごとの行（事業所得。asset_rows.py）：事業所得の減価償却費を決められない資産・経理方式の問題があれば行の全部を対象外、
        # 減価償却費を未確定にした1か所（措法28の2 の青色・年の上限、除却の超える部分、経理方式）は行も未確定
        row_reasons = [_reason(t, r) for t, r in ct.problems] + [
            _reason(t, r) for t, r, vs in s.problems[problems_before:] if V_BIZ_DEP in vs
        ]
        row_missing = [sp_ for sp_, vs in s.missing[missing_before:] if V_BIZ_DEP in vs]
        if "biz" in side_of.values():
            row_missing += list(ct.splits)
        res.write_rows(out, pid, list({sp_.id: sp_ for sp_ in row_missing}.values()), row_reasons)
        for side in SIDES:
            s.dep[side] += res.expense.get(side, 0)
            s.rev[side] += res.revenue.get(side, 0)
            s.exp[side] += res.selling_expense.get(side, 0)
            s.brk.add_exp(side, "asset_loss", res.selling_expense.get(side, 0))
            s.ids[side] |= res.ids.get(side, set())
            s.st[side] |= res.states.get(side, set())
            s.dep_basis.setdefault(side, []).extend(res.basis.get(side, ()))
        # 除却損（所法51）：事業はその全額、業務（業務に係る雑所得・事業でない不動産所得）はその所得の金額が限度（所法51④）
        rent_is_business = bool(rent_scale.value) if rent_scale is not None else False
        for side, loss in [*res.disposal_loss.items(), *s.casualty_loss.items()]:  # 業務用の土地等の災害等の損失（_business_casualties）も同じ
            business_scale = side == "biz" or (side == "rental" and rent_is_business)
            if not business_scale:
                loss = min(loss, max(0, s.rev[side] - s.exp[side] - s.dep[side]))
            s.exp[side] += loss
            s.brk.add_exp(side, "asset_loss", loss)
        # 消費税等（必要経費。税抜のときの資産の仮払消費税等も足す）
        tax_sides = {side_of[b] for b in bids_of.get(pid, [])}
        by_bid = tax_expense_by_business(ctx, pid, ct, bids_of.get(pid, []))
        if by_bid is not None:
            # 業務ごとの内訳（ct_return.attributes.business_breakdown）：業務の所得の側ごとに入れる
            per_bid, ct_ids, ct_problems = by_bid
            total = 0
            for b, amt in sorted(per_bid.items()):
                s.exp[side_of[b]] += amt
                s.brk.add_exp(side_of[b], "consumption_tax", amt)
            if not ct_problems:
                tax_sides_used = {side_of[b] for b in per_bid}
                for sd_ in tax_sides_used:
                    s.ids[sd_] |= set(ct_ids) | ct.ids
                    s.st[sd_] |= ct.states
                tax_sides = tax_sides_used if not res.prepaid_tax else tax_sides
        else:
            total, ct_ids, ct_problems = tax_expense(ctx, pid, ct, bids_of.get(pid, []))
        for text, rids in ct_problems:
            s.problems.append((text, rids, both))
        prepaid = sum(res.prepaid_tax.values())
        for sp_ in ct.splits:  # 経理方式の一次情報・語彙がなく値が分かれる（consumption.py）
            for side in tax_sides:
                s.missing.append((sp_, tuple(SIDE_VARS[side])))
        if total or prepaid:
            # 税抜の資産の仮払消費税等は資産の所得の側へ
            for side, amt in res.prepaid_tax.items():
                s.exp[side] += amt
                s.brk.add_exp(side, "consumption_tax", amt)
            side = sorted(tax_sides)[0]
            s.exp[side] += total
            s.brk.add_exp(side, "consumption_tax", total)
            for sd_ in tax_sides:
                s.ids[sd_] |= set(ct_ids) | ct.ids
                s.st[sd_] |= ct.states
            if len(tax_sides) > 1 and total:
                # 消費税等の額（人ごとの申告書）を所得の種類ごとに分ける語彙がない：分け方で各所得が変わるので未確定（全部を1つの側に入れた値を書く）
                sp_ = undetermined(
                    f"事実:所得の種類ごとの消費税等の額:{pid}:{ctx.year}",
                    Means.FACT,
                    {"person": pid, "ct_return_ids": list(ct_ids), "入力": "消費税等の額のうち各所得（事業・業務に係る雑・不動産）の業務の分（ct_return.attributes.business_breakdown を書けば決まる）"},
                )
                for sd_ in tax_sides:
                    s.missing.append((sp_, tuple(SIDE_VARS[sd_])))
        # 棚卸資産の売上原価・家事消費等・貸倒れ（inventory.py。IK-108〜IK-111）
        _inventory_and_bad_debts(ctx, pid, s, side_of, by_biz, owners, blue_st, blue_splits, rent_is_business)
        # 業務に係る雑所得の報酬の源泉徴収税額（第一表 60 の材料。tax の源泉徴収税額と同じく受取の日の年分：IK-111）
        for r in ctx.records("business_receipt"):
            if r["roles"]["recipient"] != pid or _date(r["when"]["on"]).year != ctx.year or side_of.get(r["attributes"]["business_id"]) != "misc":
                continue
            s.misc_withhold_ids.append(r["id"])
            if "withholding_tax" in r["amounts"]:
                s.misc_withhold += int(r["amounts"]["withholding_tax"])
            else:
                s.misc_withhold_missing.append(r["id"])
        staged.append((pid, s, side_of, fam_pay, rent_scale, rent_is_business, interest_recs, by_biz))
    # 所法56：受取側の対価と必要経費を「ないものとみなし」、受取側の必要経費を支払側に移す（全員の集計の後。専従者控除の限度の前）
    _apply_56(ctx, {x[0]: x[1] for x in staged}, {x[0]: x[2] for x in staged})
    allowed: dict[tuple[str, str, str], tuple[int, list[Split]]] = {}  # (事業主, 専従者, 業務) → 青色事業専従者給与として認められる額
    for pid, s, side_of, fam_pay, rent_scale, rent_is_business, interest_recs, by_biz in staged:
        # 専従者
        before_deemed = {e: len(v) for e, v in deemed.items()}
        _family_employees(ctx, pid, s, side_of, fam_pay, rent_scale, deemed, bids_of.get(pid, []), allowed)
        for e, v in deemed.items():
            if len(v) > before_deemed.get(e, 0):
                deemed_from.setdefault(e, set()).add(pid)
        # 書き出し
        excluded: set[str] = set()
        for text, rids, variables in s.problems:
            for v in variables:
                out.exclude(pid, _reason(text, rids), v)
                excluded.add(v)
            if any(v in variables for side in ("biz", "rental") for v in SIDE_VARS[side]):
                tainted.setdefault(pid, []).append(_reason(text, rids))  # 事業専従者控除額の基礎（所法57③）が対象外
        for split, variables in s.missing:
            if any(v in variables for side in ("biz", "rental") for v in (*SIDE_VARS[side], V_BIZ_FAM_DED, V_RENT_FAM_DED)):
                unsure.setdefault(pid, []).append(split)  # 事業専従者控除額の基礎が未確定なら、みなし給与も未確定
        for side, (rv, ev, dv) in SIDE_VARS.items():
            if any(v > INT32_MAX for v in (abs(s.rev[side]), abs(s.exp[side]), abs(s.dep[side]))):
                for v in (rv, ev, dv):
                    out.exclude(pid, _reason("業務の売上・必要経費の合計が判定コアの整数の範囲を超える", tuple(sorted(s.ids[side]))), v)
                    excluded.add(v)
                if side in ("biz", "rental"):
                    tainted.setdefault(pid, []).append(_reason("業務の売上・必要経費の合計が判定コアの整数の範囲を超える", tuple(sorted(s.ids[side]))))
            out.set(rv, pid, 0 if rv in excluded else max(0, s.rev[side]), s.ids[side], s.st[side], missing=_missing_for(s, rv))
            out.set(ev, pid, 0 if ev in excluded else max(0, s.exp[side]), s.ids[side], s.st[side], missing=_missing_for(s, ev))
            out.set(dv, pid, 0 if dv in excluded else s.dep[side], s.ids[side], s.st[side], missing=_missing_for(s, dv), basis=s.dep_basis.get(side, ()))
            # 消費税等の還付で必要経費が負になるときは、総収入金額に回す（経理通達8。金額の入力変数は0以上の整数）
            if s.exp[side] < 0 and ev not in excluded:
                old = out.values[(rv, pid)]
                out.values[(rv, pid)] = dataclasses.replace(old, value=s.rev[side] - s.exp[side])
            # 総収入金額・必要経費の内訳（breakdown.py。様式の科目：UO19）。総収入金額・必要経費が対象外なら内訳も対象外
            brk_reasons = [_reason(text, rids) for text, rids, variables in s.problems if rv in variables or ev in variables]
            if (rv in excluded or ev in excluded) and not brk_reasons:
                brk_reasons = [_reason("業務の売上・必要経費の合計が判定コアの整数の範囲を超える", tuple(sorted(s.ids[side])))]
            write_breakdown(
                out, pid, s.brk, side, (out.values[(rv, pid)].value, out.values[(ev, pid)].value), s.ids[side], s.st[side],
                (*_missing_for(s, rv), *_missing_for(s, ev)), brk_reasons,
            )  # fmt: skip
            # 売上原価の欄の材料（期首・期末の棚卸高・仕入金額・売上原価。IK-108）
            write_cost_of_sales(
                out, pid, s.brk, side, s.inv.get(side, (0, 0)), s.ids[side], s.st[side], (*_missing_for(s, rv), *_missing_for(s, ev)), brk_reasons
            )  # fmt: skip
        for v, side, field_name in ((V_BIZ_SALARY, "biz", "salary"), (V_RENT_SALARY, "rental", "salary"), (V_BIZ_FAM_DED, "biz", "deduction"), (V_RENT_FAM_DED, "rental", "deduction")):
            out.set(v, pid, 0 if v in excluded else getattr(s, field_name)[side], s.ids[side], s.st[side], missing=_missing_for(s, v))
        if s.misc_withhold_missing:
            out.exclude(pid, _reason(MISC_WITHHOLD_MISSING_REASON, s.misc_withhold_missing), V_MISC_WITHHOLD)
        out.set(V_MISC_WITHHOLD, pid, 0 if s.misc_withhold_missing else s.misc_withhold, s.misc_withhold_ids, s.st["misc"], missing=_missing_for(s, V_MISC_REV))
        # 不動産の貸付けの事業的規模・通算の制限の材料
        out.set(V_RENT_SCALE, pid, rent_is_business, tuple(rent_scale.record_ids) if rent_scale is not None else (), set(rent_scale.states) if rent_scale is not None else ())
        land, land_ids = _land_interest(ctx, pid, interest_recs)
        # 措令26の6②（選択.不動産所得の計上 の loan_interest_allocation。rental_choices.py：IK-119）
        land_choice_miss: tuple[Split, ...] = ()
        choice26 = _rc.land_interest_choice(ctx, pid, interest_recs)
        if choice26 is not None:
            land, extra_ids, land_choice_miss, land_choice_problems = choice26
            land_ids = tuple(sorted(set(land_ids) | set(extra_ids)))
            for text, rids in land_choice_problems:
                out.exclude(pid, _reason(text, rids), V_RENT_LAND_INT)
        villa, villa_ids = _all_villa(ctx, pid)
        loss_before = s.rev["rental"] - s.exp["rental"] - s.dep["rental"] - s.salary["rental"] - s.deduction["rental"]
        # 組合事業・信託（措法41の4の2）と国外中古建物（措法41の4の3）の損失：所法26② の上でも生じなかったものとみなす（IK-104。rental_special.py）
        sp_deemed, sp_ids, sp_problems, sp_splits = _special_rental(ctx, pid, s)
        for text, rids in sp_problems:
            out.exclude(pid, _reason(text, rids), V_RENT_SPECIAL)
        out.set(
            V_RENT_SPECIAL, pid, 0 if sp_problems else sp_deemed.total, sorted(sp_ids), s.st["rental"],
            missing=tuple(sp_splits) + _missing_for(s, V_RENT_EXP),
        )  # fmt: skip
        if not sp_problems:
            loss_before += sp_deemed.total
        land_miss: tuple[Split, ...] = ()
        villa_miss: tuple[Split, ...] = ()
        villa_loss = 0
        if land is None:
            # 土地等の負債とそれ以外の負債が混ざる：利子の支出が借入れを指していれば（business_expense.attributes.loan_id。2026-11-12 の語彙）
            # その借入れの目的の資産で分ける。指していなければ土地等の負債の利子は0〜利子の全部の両端で、値が違えば未確定（c-入力）
            total_int = sum(r["amounts"]["amount"] for r in interest_recs)
            land = total_int
            linked_land = _land_interest_by_loan(ctx, interest_recs)
            if linked_land is not None:
                land = linked_land
            elif loss_before < 0 and total_int:
                land_miss = (undetermined(
                    f"事実:土地等の負債の利子:{pid}:{ctx.year}", Means.FACT,
                    {"person": pid, "loan_ids": list(land_ids), "入力": "借入金の利子の支出（business_expense）ごとの借入れ（attributes.loan_id を書けば決まる）"},
                    ("土地等の負債の利子は0", "利子の全部"),
                ),)
        if villa is None:
            # 別荘等の貸付けとそれ以外が混ざる：物件ごとの収支（property_id。2026-11-12 の語彙）で別荘等の分を求める（_villa_by_property）。
            # 求められなければ、損失の全部が別荘等の分か・どれも違うかの両端で値が違えば未確定（c-入力）
            villa = False
            if loss_before < 0:
                by_prop = _villa_by_property(ctx, pid, s)
                if by_prop is None:
                    villa_miss = (undetermined(
                        f"事実:別荘等の貸付けの損失:{pid}:{ctx.year}", Means.FACT,
                        {"person": pid, "property_ids": list(villa_ids), "入力": "物件ごとの総収入金額と必要経費（rent_flow・business_expense・depreciable_asset の property_id を書けば決まる）"},
                        ("損失は別荘等の分でない", "損失の全部が別荘等の分"),
                    ),)
                else:
                    v_net, o_net = by_prop
                    if v_net < 0 and o_net >= 0:
                        villa = True  # 損失は全部が別荘等の分（内部通算の読み：概念 所得税.別荘等の貸付けに係る損失の額 の注）
                    elif v_net < 0:
                        villa_loss = -v_net
                        if land:
                            villa_miss = (undetermined(
                                f"一次情報:別荘等の損失と土地等の負債の利子の重なり:{pid}:{ctx.year}", Means.PRIMARY_SOURCE,
                                {"person": pid, "property_ids": list(villa_ids), "事項": "別荘等の貸付けの損失（所法69②）と土地等の負債の利子（措法41の4）がともにあるときの、生じなかったものとみなす額の重なりの扱い"},
                                ("合計", "大きい方"),
                            ),)
                    if sp_deemed.total:
                        # 別荘等の物件ごとの収支（所法69②）と、組合事業・国外中古建物の生じなかったものとみなす損失の重なりの扱いの一次情報がない
                        villa_miss = villa_miss + (undetermined(
                            f"一次情報:別荘等の損失と組合事業等・国外中古建物の損失の重なり:{pid}:{ctx.year}", Means.PRIMARY_SOURCE,
                            {"person": pid, "property_ids": list(villa_ids), "事項": "別荘等の貸付けの損失（所法69②）と、措法41の4の2・41の4の3 で生じなかったものとみなす損失がともにあるときの物件ごとの収支"},
                            ("物件の収支のまま", "生じなかったものとみなした後の収支"),
                        ),)
        if land and sp_deemed.by_arrangement and not sp_problems:
            # 措通41の4−4：組合事業・信託の業務の区分ごとに、土地等の負債の利子のうち生じなかったものとみなされる金額を超える部分だけを数える
            cut, unlinked = _arrangement_land_interest(ctx, pid, interest_recs, sp_deemed)
            land = max(0, land - cut)
            if unlinked:
                land_miss = land_miss + (undetermined(
                    f"事実:組合事業等の土地等の負債の利子:{pid}:{ctx.year}", Means.FACT,
                    {"person": pid, "record_ids": unlinked, "入力": "借入金の利子の支出（business_expense）ごとの借入れ（attributes.loan_id）か物件（property_id）"},
                    ("組合事業等の分でない", "組合事業等の分"),
                ),)
        out.set(V_RENT_LAND_INT, pid, land, land_ids, (), missing=land_miss + land_choice_miss + _missing_for(s, V_RENT_EXP))
        out.set(V_RENT_ALL_VILLA, pid, bool(villa), villa_ids, (), missing=villa_miss)
        out.set(V_RENT_VILLA_LOSS, pid, villa_loss, villa_ids, (), missing=villa_miss)
        # 家内労働者等（給与所得がある人も特例の額を給与所得控除額で減らして当てる：variables.py）
        hd = ctx.decision(K_HOME, pid) if any(r["kind"] == "business_receipt" for bid, rs in by_biz.items() if owners.get(bid) == pid for r in rs) else None
        is_home = bool(hd.value) if hd is not None else False
        out.set(V_HOME, pid, is_home, hd.record_ids if hd else (), hd.states if hd else ())
    # 事業専従者控除（専従者の側の給与の収入金額とみなす額）
    for pid in ctx.persons:
        amts = deemed.get(pid, [])
        total_deemed = sum(a for a, _, _ in amts)
        ids = [i for _, rs, _ in amts for i in rs]
        st: set[State] = set()
        for _, _, s_ in amts:
            st |= s_
        # 所法57④：専従者の給与所得に係る収入金額とみなす（kyuyo が段階評価で読んで給与等の収入金額に足す）。
        # 事業主の事業専従者控除額が対象外なら、その額は信じられないので、みなし給与も対象外にする
        bad = [r for owner in sorted(deemed_from.get(pid, ())) for r in tainted.get(owner, [])]
        for r in bad:
            out.exclude(pid, r, V_FAM_DEEMED)
        if bad:
            total_deemed = 0
        miss = tuple(x for owner in sorted(deemed_from.get(pid, ())) for x in unsure.get(owner, []))
        out.set(V_FAM_DEEMED, pid, total_deemed, ids, st, missing=miss)
    _family_salary_received(ctx, out, staged, allowed, tainted, unsure)
    # 専従者の側の事業主と専従者給与等の額（breakdown.py。第二表の事業専従者の行：UO23）
    write_employers(out, ctx.persons, allowed, deemed, deemed_from, tainted, unsure)


FAMILY_SALARY_BID_REASON = (
    "入力の不足：家族（役割 payer）が支払った給与（salary_payment）に支払った人の業務（attributes.payer_business_id）がなく、"
    "支払った人の業務が1つに決まらない（所法56 の事業からの対価かを決められない）"
)
FAMILY_SALARY_PAYER_REASON = "入力の矛盾：給与（salary_payment）を支払った家族（役割 payer）がその年分に生存していない"


def _family_salary_received(
    ctx: YearContext,
    out: ModuleInputs,
    staged: list[tuple[Any, ...]],
    allowed: Mapping[tuple[str, str, str], tuple[int, list[Split]]],
    tainted: Mapping[str, list[OutOfScopeReason]],
    unsure: Mapping[str, list[Split]],
) -> None:
    """所法56 の受取側の給与（2026-11-12）：生計を一にする親族の事業から受けた給与のうち、青色事業専従者給与（所法57①）として
    必要経費に算入される額を超える部分は、受け取った人の各種所得の金額の計算上ないものとみなす。kyuyo が段で読んで給与等の収入金額から引く。

    - 給与の支払（salary_payment）の役割 payer が支払った家族、attributes.payer_business_id がその業務（なければ支払った人の業務が1つならそれ）。
    - 事業（事業所得・事業的規模の不動産所得）：白色なら全額、青色なら認められる額（届出・相当性の範囲）を超える部分。事業専従者控除のみなし給与は別（所法57④）。
    - 業務（雑所得・事業的規模でない不動産所得）：所法56 の当てはめの読みが分かれる（_reading_56。0 と全額）。
    - 生計を一にする親族でなければ除かない（通常の給与）。支払った人の事業所得等が対象外・未確定なら、その理由・分かれ目を写す。
    """
    info = {x[0]: x for x in staged}
    for q in ctx.persons:
        groups: dict[tuple[str, str], int] = {}
        ids: list[str] = []
        st: set[State] = set()
        miss: list[Split] = []
        reasons: list[OutOfScopeReason] = []
        for r in sorted(ctx.records("salary_payment"), key=lambda r: r["id"]):
            p = r["roles"].get("payer")
            if r["roles"]["recipient"] != q or p is None or p == q or _date(r["attributes"]["due_on"]).year != ctx.year:
                continue
            ids.append(r["id"])
            st |= _states([r])
            if p not in info:
                reasons.append(_reason(FAMILY_SALARY_PAYER_REASON, (r["id"],)))
                continue
            _, ps, side_of, fam_pay, _, rent_is_business, _, _ = info[p]
            bid = r["attributes"].get("payer_business_id")
            if bid is None and len(side_of) == 1:
                bid = next(iter(side_of))
            if bid is None or bid not in side_of:
                reasons.append(_reason(FAMILY_SALARY_BID_REASON, (r["id"],)))
                continue
            sd = ctx.decision(K_SEIKEI, pair_key(p, q))
            ids += list(sd.record_ids)
            st |= set(sd.states)
            if not (sd.value and is_relative(ctx, p, q, _year_end_or_death(ctx, p))):
                continue  # 生計を一にする親族でない：通常の給与
            side = side_of[bid]
            if not (side == "biz" or (side == "rental" and rent_is_business)):
                miss.append(_reading_56(p, q, r["id"]))  # 業務からの給与：読みが分かれる（数えたまま）
                continue
            groups[(p, bid)] = groups.get((p, bid), 0) + r["amounts"]["gross"]
        total = 0
        for (p, bid), paid in sorted(groups.items()):
            ok_amount, splits = allowed.get((p, q, bid), (0, []))
            total += max(0, paid - ok_amount)
            miss += splits
            reasons += tainted.get(p, [])
            miss += unsure.get(p, [])
        for reason in reasons:
            out.exclude(q, reason, V_FAMILY_SALARY_OUT)
        out.set(V_FAMILY_SALARY_OUT, q, 0 if reasons else total, ids, st, missing=unique_splits(miss))


def unique_splits(splits: Iterable[Split]) -> tuple[Split, ...]:
    """分かれ目の重なりを順を保って除く（2026-11-12）。Split の target は dict で hash できないので、dict.fromkeys ではなく等しさで比べる
    （以前は dict.fromkeys で、受取側の給与に分かれ目がある中間表現〔例 08〕の評価が TypeError で止まっていた）。"""
    seen: list[Split] = []
    for s in splits:
        if s not in seen:
            seen.append(s)
    return tuple(seen)


def _proviso(ctx: YearContext, pid: str, emp: str, bid: str) -> tuple[set[bool], Split | None]:
    """所令165①ただし書（青色だけ）：事業が年を通じて営まれなかった（一）か、従事する者が年を通じて従事できなかった（二）ときは、
    従事することができると認められる期間の2分の1を超える期間専ら従事すれば足りる。戻り値：候補ごとの結論の集合と、分かれたときの1か所。

    - 従事することができた期間：（一）業務の期間（business の when）と事業主の生存の期間のその年の部分。（二）従事する者の死亡ならその日まで。
      長期の病気・婚姻・その他（就職・退職を含む：質疑応答事例）は、従事することができた期間の記録（available_period）があればその期間、
      なければ「従事の記録の期間」と「（一）の期間」の両方で評価する（分かれれば c-入力）。
    - 月で数えるか日で数えるかの一次情報がない（質疑応答事例も書かない：aoiro §4.1・verification §5）ので両方で評価する。
    """
    y0, y1 = _dt.date(ctx.year, 1, 1), _dt.date(ctx.year, 12, 31)
    biz = next((r for r in ctx.records("business") if r["id"] == bid), None)
    b0 = max(y0, _date(biz["when"]["from_on"])) if biz else y0
    b1 = min(y1, _date(biz["when"]["to_on"])) if biz and biz["when"].get("to_on") else y1
    death = ctx.death_on(pid)
    if death:
        b1 = min(b1, death)
    engs = [
        r
        for r in ctx.records("business_engagement")
        if r["roles"]["business_owner"] == pid and r["roles"]["relative"] == emp and r["attributes"]["business_id"] == bid
    ]
    spans = normalize(
        (max(y0, _date(r["when"]["from_on"])), min(y1, _date(r["when"]["to_on"]) if r["when"].get("to_on") else y1)) for r in engs
    )
    spans = [(a, b) for a, b in spans if a <= b]
    e_death = ctx.death_on(emp)
    if e_death:
        b1 = min(b1, e_death)
    reasons = {r["attributes"].get("interruption_reason") for r in engs} - {None, "death"}
    # 従事することができた期間の記録（business_engagement.attributes.available_period。2026-11-12 の語彙）
    avail = normalize(
        (max(b0, _date(p["from_on"])), min(b1, _date(p["to_on"]) if p.get("to_on") else b1))
        for p in (r["attributes"].get("available_period") for r in engs)
        if p
    )
    avail = [(a, b) for a, b in avail if a <= b]
    whole_year = (b0, b1) == (y0, y1)
    if whole_year and not reasons and not avail:
        return {False}, None  # ただし書の事由がない（本文の6月で判定済み）
    possible: list[list[tuple[_dt.date, _dt.date]]] = [[(b0, b1)]]
    if avail:
        possible = [avail]  # 所令165①二：従事することができると認められる期間（記録どおり）
    elif reasons and spans:
        possible.append([(max(b0, spans[0][0]), min(b1, spans[-1][1]))])
    results: dict[tuple[str, int], bool] = {}
    for i, per in enumerate(possible):
        engaged = intersect(spans, per)
        days_e = sum((b - a).days + 1 for a, b in engaged)
        days_p = sum((b - a).days + 1 for a, b in per)
        months_e = sum(calendar_months(a, b) for a, b in engaged)
        months_p = sum(calendar_months(a, b) for a, b in per)
        results[("日", i)] = days_e * 2 > days_p
        results[("月", i)] = months_e * 2 > months_p
    outs = set(results.values())
    if len(outs) == 1:
        return outs, None
    by_period = len({v for (k, i), v in results.items() if k == "日"}) > 1 or len({v for (k, i), v in results.items() if k == "月"}) > 1
    if by_period and len(possible) > 1:
        return outs, undetermined(
            f"事実:従事することができた期間:{pid}:{emp}:{bid}:{ctx.year}",
            Means.FACT,
            {"business_owner": pid, "relative": emp, "business_id": bid, "入力": "長期の病気・婚姻・就職などで事業に従事することができると認められる期間（所令165①二。business_engagement.attributes.available_period を書けば決まる）"},
            ("専ら従事する者に当たる", "当たらない"),
        )
    return outs, undetermined(
        f"一次情報:所令165の期間の数え方:{pid}:{emp}:{bid}:{ctx.year}",
        Means.PRIMARY_SOURCE,
        {"business_owner": pid, "relative": emp, "business_id": bid, "事項": "所令165①ただし書の2分の1を超える期間を月で数えるか日で数えるか"},
        ("専ら従事する者に当たる", "当たらない"),
    )


def _work_shares(
    ctx: YearContext, pid: str, emp: str, side_of: Mapping[str, str], by_side: Mapping[str, Any]
) -> dict[str, Fraction] | None:
    """所令167 の従事した分量（business_engagement.attributes.work_share）を所得の側ごとに足す。その年の従事の記録の全部に書かれていなければ None。"""
    per_bid: dict[str, Fraction] = {}  # 業務ごとに、その年の最後の従事の記録の割合
    for r in sorted(ctx.records("business_engagement"), key=lambda r: (r["when"]["from_on"], r["id"])):
        if r["roles"]["business_owner"] != pid or r["roles"]["relative"] != emp or not overlaps_year(r.get("when"), ctx.year):
            continue
        bid = r["attributes"]["business_id"]
        if side_of.get(bid) not in by_side:
            continue
        ws = r["attributes"].get("work_share")
        if ws is None:
            return None
        per_bid[bid] = Fraction(ws["num"], ws["den"])
    out: dict[str, Fraction] = dict.fromkeys(by_side, Fraction(0))
    for bid, share in per_bid.items():
        out[side_of[bid]] += share
    return out


def _family_employees(
    ctx: YearContext,
    pid: str,
    s: _Sides,
    side_of: Mapping[str, str],
    fam_pay: Mapping[str, list[Mapping[str, Any]]],
    rent_scale: Any,
    deemed: dict[str, list[tuple[int, list[str], set[State]]]],
    bids: list[str],
    allowed: dict[tuple[str, str, str], tuple[int, list[Split]]] | None = None,
) -> None:
    """専従者（所法57）と、要件を満たさない家族への給与（所法56）。結果は s と deemed に書く。

    - 所法57 は事業（事業所得・事業的規模の不動産所得）に限る。業務からの生計を一にする親族への給与は所法56 の当てはめの読みが分かれる（両方で評価）。
    - 青色：要件（親族・生計・15歳以上・専ら従事〔所令165〕・届出〔所法57②〕）を満たす給与のうち、届出の金額と相当性の範囲内を必要経費にする。
      満たさない給与・範囲を超える部分は所法56 で必要経費にしない（所法57① は所法56 の例外：「前条の規定にかかわらず」）。
    - 白色：生計を一にする親族への給与は所法56 で必要経費にせず、要件を満たす事業専従者ごとに控除額（所法57③）。二以上の事業に従事する場合は
      所令166②（所得の合計と専従者の数で限度）と所令167（従事した分量で配分。明らかでなければ均等）。
    - 受取側の給与（salary_payment）は kyuyo の入力で、ここからは除けない（README の申し送り）。
    """
    if not fam_pay and not any(r["roles"]["business_owner"] == pid for r in ctx.records("business_engagement")):
        return
    blue_splits: list[Split] = []
    state, _, _ = blue_state(ctx, pid, splits=blue_splits)
    rent_is_business = bool(rent_scale.value) if rent_scale is not None else False
    approved = state == BLUE_APPROVED
    for sp_ in blue_splits:  # 青色の承認が読みで分かれる：専従者給与・控除の側を未確定にする
        for side in ("biz", "rental"):
            s.missing.append((sp_, (*SIDE_VARS[side], V_BIZ_SALARY if side == "biz" else V_RENT_SALARY, V_BIZ_FAM_DED if side == "biz" else V_RENT_FAM_DED)))
    fparams = ctx.parameters.所得税.事業専従者控除
    limit_age = int(fparams.対象の年齢)
    need_months = int(fparams.従事の月数の基準)
    year_end = _dt.date(ctx.year, 12, 31)
    death = ctx.death_on(pid)
    check_on = min(year_end, death) if death else year_end
    reasonable = {j["subject"]["employee"]: j for j in ctx.judgments(K_REASONABLE) if j["subject"]["employer"] == pid and overlaps_year(j.get("when"), ctx.year)}

    def family_of(emp: str, side: str) -> tuple[bool, list[str]]:
        """生計を一にする親族か（所法56・57）。"""
        sd = ctx.decision(K_SEIKEI, pair_key(pid, emp))
        s.st[side] |= set(sd.states)
        return bool(sd.value) and is_relative(ctx, pid, emp, check_on), list(sd.record_ids)

    def engaged(emp: str, bid: str) -> tuple[bool, list[str], Split | None]:
        """15歳以上（所法57⑦）で専ら従事する（所令165①。ただし書は青色だけ）か。分かれたら (True, 記録, 1か所)。"""
        if age_on(ctx, emp, check_on) < limit_age:
            return False, [], None
        months, eng_ids, _ = engagement_months(ctx, pid, emp, bid)
        if not eng_ids:
            return False, [], None
        if months > need_months:
            return True, eng_ids, None
        if not approved:
            return False, eng_ids, None
        outs, split = _proviso(ctx, pid, emp, bid)
        return (True in outs), eng_ids, split

    def is_business(side: str) -> bool:
        return side == "biz" or (side == "rental" and rent_is_business)

    salary_var = {"biz": V_BIZ_SALARY, "rental": V_RENT_SALARY}
    deduction_var = {"biz": V_BIZ_FAM_DED, "rental": V_RENT_FAM_DED}
    for bid, recs in sorted(fam_pay.items()):
        side = side_of[bid]
        by_emp: dict[str, list[Mapping[str, Any]]] = {}
        for r in recs:
            by_emp.setdefault(r["roles"]["recipient"], []).append(r)
        for emp, pays in sorted(by_emp.items()):
            rids = [r["id"] for r in pays]
            paid = sum(r["amounts"]["amount"] for r in pays)
            fam, f_ids = family_of(emp, side)
            s.ids[side] |= set(rids) | set(f_ids)
            if not fam:  # 生計を一にする親族でなければ通常の給与として必要経費
                s.exp[side] += paid
                s.brk.add_exp(side, "payroll_wages", paid)
                continue
            if not is_business(side):
                # 業務からの給与：所法57 の適用はなく、所法56 の当てはめが読みで分かれる（数えた値に未確定を付ける）
                s.exp[side] += paid
                s.brk.add_exp(side, "payroll_wages", paid)
                for r in pays:
                    s.missing.append((_reading_56(pid, emp, r["id"]), tuple(SIDE_VARS[side])))
                continue
            if not approved:
                continue  # 白色：所法56 で必要経費にしない（事業専従者控除は下）
            ok, e_ids, split = engaged(emp, bid)
            s.ids[side] |= set(e_ids)
            if not ok:
                continue  # 青色事業専従者でない親族への給与：所法56 で必要経費にしない
            filed, n_ids, monthly = within_notice(ctx, pid, emp)
            s.ids[side] |= set(n_ids)
            if not filed:
                continue  # 届出が期限までにない（所法57②）：所法56 で必要経費にしない
            ceilings: list[int] = []
            if monthly is not None:
                months, _, _ = engagement_months(ctx, pid, emp, bid)
                ceilings.append(int(monthly) * months)
            j = reasonable.get(emp)
            if j is not None:
                s.ids[side].add(j["id"])
                if j["value"].get("reasonable_amount") is not None:
                    ceilings.append(int(j["value"]["reasonable_amount"]))
            ok_amount = min([paid, *ceilings])
            s.salary[side] += ok_amount  # 届出の金額・相当と認められる額を超える部分は所法56 で必要経費にしない（所法57①）
            if split is not None:
                s.missing.append((split, (*SIDE_VARS[side], salary_var[side])))
            if allowed is not None:  # 受取側（所法56・57①）：青色事業専従者給与として給与所得の収入金額になる額
                allowed[(pid, emp, bid)] = (ok_amount, [split] if split is not None else [])
    if approved:
        return
    # 白色（事業専従者控除：所法57③、所令166②・167）
    per_emp: dict[str, dict[str, tuple[int, list[str]]]] = {}  # 専従者 → 所得の側 → (従事の月数, 記録)
    for bid in bids:
        side = side_of[bid]
        if not is_business(side):
            continue
        employees = sorted({r["roles"]["relative"] for r in ctx.records("business_engagement") if r["roles"]["business_owner"] == pid and r["attributes"]["business_id"] == bid and overlaps_year(r.get("when"), ctx.year)})
        for emp in employees:
            fam, f_ids = family_of(emp, side)
            if not fam:
                continue
            ok, e_ids, _ = engaged(emp, bid)
            if not ok:
                continue  # 事業専従者の要件を満たさない：控除はない（給与は所法56 で必要経費にしない）
            months, _, _ = engagement_months(ctx, pid, emp, bid)
            prev_m, prev_ids = per_emp.setdefault(emp, {}).get(side, (0, []))
            per_emp[emp][side] = (prev_m + months, prev_ids + f_ids + e_ids)
    if not per_emp:
        return
    sides_used = sorted({side for d in per_emp.values() for side in d})
    base = sum(s.rev[side] - s.exp[side] - s.dep[side] for side in sides_used)  # 所令166②・所基通57−2（赤字は黒字と相殺）
    if base <= 0:
        return
    per = Fraction(base, len(per_emp) + 1)
    for emp, by_side in sorted(per_emp.items()):
        cap = int(fparams.配偶者の額) if is_spouse(ctx, pid, emp, year_end) else int(fparams.その他の親族の額)
        amount = _round_expense(ctx, min(Fraction(cap), per))
        ids = [i for _, (_, x) in sorted(by_side.items()) for i in x]
        if len(by_side) == 1:
            side = next(iter(by_side))
            s.deduction[side] += amount
            s.ids[side] |= set(ids)
        else:
            # 所令167：従事した分量に応じて配分（明らかでなければ均等）。分量を入力する語彙がないので、従事の記録の月数の比と均等の両方で評価する
            months = {side: m for side, (m, _) in by_side.items()}
            total_m = sum(months.values())
            first, second = sorted(by_side)
            equal = _round_expense(ctx, Fraction(amount, 2))
            by_months = _round_expense(ctx, Fraction(amount * months[first], total_m)) if total_m else equal
            shares = _work_shares(ctx, pid, emp, side_of, by_side)
            if shares is not None:
                # 従事した分量の記録（business_engagement.attributes.work_share。2026-11-12 の語彙）：その比で配分する（所令167）
                total_share = shares[first] + shares[second]
                equal = _round_expense(ctx, amount * shares[first] / total_share) if total_share else equal
                by_months = equal
            s.deduction[first] += equal
            s.deduction[second] += amount - equal
            for side in by_side:
                s.ids[side] |= set(ids)
            if by_months != equal:
                split = undetermined(
                    f"事実:事業専従者の従事した分量:{pid}:{emp}:{ctx.year}",
                    Means.FACT,
                    {"business_owner": pid, "relative": emp, "入力": "二以上の事業に従事した事業専従者のそれぞれの事業に従事した分量（所令167。business_engagement.attributes.work_share を書けば決まる）"},
                    ("均等", "従事の記録の月数の比"),
                )
                for side in by_side:
                    s.missing.append((split, (*SIDE_VARS[side], deduction_var[side])))
        deemed.setdefault(emp, []).append((amount, ids, set().union(*(s.st[side] for side in by_side))))


CASUALTY_UNRECORDED_REASON = (
    "業務用の減価償却資産の損壊による価値の減少（資産台帳の滅失・除却として記録されていないもの）の損失の金額は、所令142一の取得費（損失の生じた日の"
    "未償却残高）から直後の価額と発生資材の価額を控除した額（所基通51−2）だが、年の中途の損失の日までの償却費と、損失の後の償却の基礎の扱いの一次情報が docs にない"
)
CASUALTY_OTHER_REASON = (
    "業務用の資産の災害等の損失で、資産（asset_id）が資産台帳にも賃貸物件の土地等にも結びつかない。棚卸資産の損失は所法51 の対象でなく売上原価の側"
    "（所法47。取得していない：kojo-misc §3）で、どちらの資産かを決められない"
)
CASUALTY_VALUE_REASON = (
    "入力の不足：業務用の土地等の災害等の損失（casualty）に、損失の直後の価額（amounts.post_loss_value）か取得費（amounts.acquisition_cost "
    "又は rental_property の acquisition_cost）がない（所令142一・所基通51−2）"
)
CASUALTY_INSURANCE_REASON = "業務用の資産の災害等の損失で、事象（casualty）と資産台帳（depreciable_asset）の保険金等の額が食い違う"


def _business_casualties(ctx: YearContext, pid: str, s: _Sides, both: tuple[str, ...], side_of: Mapping[str, str]) -> None:
    """業務用の資産の災害等の損失（被災事業用資産の損失を含む。所法51①④）。雑損控除の対象ではない（所法72①：other_deductions が外す）。

    資産台帳の減価償却資産がその年に滅失・除却（disposal_type が loss・scrapping）として記録されていれば、台帳の処分（assets.py の除却損：
    未償却残高−処分価額＋費用−保険金）で必要経費に算入されるので、ここでは足さない。それ以外は損失の金額を決められないので、その業務の側を対象外にする。
    """
    assets = {a["id"]: a for a in ctx.records("depreciable_asset") if a["roles"]["owner"] == pid}
    lands = {r["id"]: r for r in ctx.records("rental_property") if r["roles"]["owner"] == pid and r["attributes"]["property_type"] in LAND_PROPERTY_TYPES}
    for c in sorted(ctx.records("casualty"), key=lambda r: r["id"]):
        if c["roles"]["owner"] != pid or not c["attributes"].get("business_use") or _year_of(c) != ctx.year:
            continue
        asset = assets.get(c["attributes"].get("asset_id", ""))
        land = lands.get(c["attributes"].get("asset_id", ""))
        if asset is None and land is not None and land["attributes"].get("business_id") in side_of:
            # 業務用の土地等（減価償却をしない固定資産）：所令142一の取得費から、直後の価額と発生資材の価額（所基通51−2）、保険金等（所法51①）を控除
            side = side_of[land["attributes"]["business_id"]]
            basis = c["amounts"].get("acquisition_cost", land["amounts"].get("acquisition_cost"))
            post = c["amounts"].get("post_loss_value")
            if basis is None or post is None:
                s.problems.append((CASUALTY_VALUE_REASON, (c["id"], land["id"]), tuple(SIDE_VARS[side])))
                continue
            loss = max(0, basis - post - c["amounts"].get("salvage_value", 0) - c["amounts"].get("insurance_recovery", 0))
            s.casualty_loss[side] = s.casualty_loss.get(side, 0) + loss
            s.ids[side] |= {c["id"], land["id"]}
            s.st[side] |= _states([c])
            continue
        bid = asset["attributes"].get("business_id") if asset is not None else None
        variables = tuple(SIDE_VARS[side_of[bid]]) if bid in side_of else both
        disposed = disposed_on(asset) if asset is not None else None
        if asset is None or disposed is None or disposed.year != ctx.year or asset["attributes"].get("disposal_type") not in ("loss", "scrapping"):
            # 損失の金額を決める一次情報がなく、候補（0〜損失の全部）を作れない：その業務の側を未確定にして、何が要るかを返す
            s.missing.append((undetermined(
                f"一次情報:業務用の資産の災害等の損失の金額:{c['id']}", Means.PRIMARY_SOURCE,
                {"person": pid, "casualty_id": c["id"], "事項": CASUALTY_UNRECORDED_REASON if asset is not None else CASUALTY_OTHER_REASON},
            ), variables))
            continue
        ins_c = c["amounts"].get("insurance_recovery")
        if ins_c is not None and ins_c != asset["amounts"].get("insurance_recovery", 0):
            s.problems.append((CASUALTY_INSURANCE_REASON, (c["id"], asset["id"]), variables))
            continue
        if bid in side_of:
            s.ids[side_of[bid]].add(c["id"])


MISC_WITHHOLD_MISSING_REASON = (
    "入力の不足：業務に係る雑所得の報酬の受取（business_receipt）に源泉徴収税額（amounts.withholding_tax）が書かれていない（0 か未記録かを区別できない。第一表 60）"
)

#: 前年以前の損失の繰越控除がありうる申告書の記載（所令180②一が二号より低くなりうる：IK-110）。
_CARRY_ITEMS = frozenset({"net_loss_total", "casualty_loss_carryforward"})


def _judged_inventory(ctx: YearContext, pid: str, bid: str) -> dict[int, tuple[bool, str]]:
    """判断.棚卸資産の有無：年分 → (有するか, 判断の ID)。"""
    out: dict[int, tuple[bool, str]] = {}
    for j in ctx.judgments(inv.J_INVENTORY):
        sub = j["subject"]
        if sub.get("person") == pid and sub.get("business_id") == bid:
            year = (j.get("when") or {}).get("tax_year")
            if isinstance(year, int) and year not in out:
                out[year] = (bool(j["value"]), j["id"])
    return out


def _inventory_and_bad_debts(
    ctx: YearContext,
    pid: str,
    s: _Sides,
    side_of: Mapping[str, str],
    by_biz: Mapping[str, list[Mapping[str, Any]]],
    owners: Mapping[str, str],
    blue_st: Any,
    blue_splits: list[Split],
    rent_is_business: bool,
) -> None:
    """棚卸資産の売上原価（所法47・37①）、家事消費等（所法39・40①一）、貸倒れ（所法51②④・所令141・所法64①）。inventory.py の純粋関数を当てる。"""
    year_end = _year_end_or_death(ctx, pid)
    counts_all = [r for r in ctx.records("inventory_count") if r["roles"]["owner"] == pid]
    notices_all = [r for r in ctx.records("inventory_method_notice") if r["roles"]["person"] == pid]
    house_all = [r for r in ctx.records("household_consumption") if r["roles"]["owner"] == pid and _year_of(r) == ctx.year]
    for bid in sorted(side_of):
        side = side_of[bid]
        if side not in ("biz", "misc"):
            continue
        biz_rec = next(r for r in ctx.records("business") if r["id"] == bid)
        start = _date(biz_rec["when"]["from_on"])
        recs = by_biz.get(bid, [])
        counts = [r for r in counts_all if r["attributes"]["business_id"] == bid]
        notices = [r for r in notices_all if r["attributes"]["business_id"] == bid]
        house = [r for r in house_all if r["attributes"]["business_id"] == bid]
        purchases = any(r["kind"] == "business_expense" and r["attributes"].get("expense_category") in inv.PURCHASE_CATEGORIES for r in recs)
        blue: dict[int, bool] = {}
        if any(n["attributes"].get("lower_of_cost") for n in notices):  # 低価法の届出があるときだけ青色の承認を読む（所令99①）
            n_splits = len(blue_splits)
            blue = {y: bool(blue_st(y)) for y in (ctx.year - 1, ctx.year)}
            for sp_ in blue_splits[n_splits:]:
                s.missing.append((sp_, tuple(SIDE_VARS[side])))
        res = inv.inventory_for(
            counts=counts, notices=notices, judgments=_judged_inventory(ctx, pid, bid), business=side == "biz", start=start,
            year=ctx.year, year_end=year_end, blue=blue, has_activity=purchases or bool(house),
        )  # fmt: skip
        if res.problem:
            s.problems.append((res.problem, tuple(res.problem_ids) or (bid,), tuple(SIDE_VARS[side])))
        elif res.relevant:
            change = res.opening - res.closing  # 売上原価＝期首＋仕入－期末（仕入は支出の年の必要経費に数えてある）
            s.exp[side] += change
            s.brk.add_exp(side, "inventory_change", change)
            o, c = s.inv.get(side, (0, 0))
            s.inv[side] = (o + res.opening, c + res.closing)
            s.ids[side] |= set(res.record_ids)
            s.st[side] |= _states([r for r in counts + notices if r["id"] in res.record_ids])
        for r in house:
            amt, _booked = inv.household_amount(r, business=side == "biz")
            if amt is None:
                s.problems.append((inv.HOUSEHOLD_PRICE_REASON, (r["id"],), tuple(SIDE_VARS[side])))
                continue
            s.rev[side] += amt
            s.brk.add_rev(side, REV_HOUSEHOLD, amt)
            s.ids[side].add(r["id"])
            s.st[side] |= _states([r])
    # 貸倒れ
    debts = [r for r in ctx.records("bad_debt") if r["roles"]["creditor"] == pid]
    deemed: dict[str, list[Mapping[str, Any]]] = {}
    for r in sorted(debts, key=lambda r: r["id"]):
        bid = r["attributes"]["business_id"]
        on_year = _year_of(r)
        ry = r["attributes"].get("revenue_tax_year")
        if bid not in side_of:
            if on_year == ctx.year or ry == ctx.year:
                s.problems.append(("貸倒れの記録（bad_debt）の業務がほかの人の業務か、業務の記録に結びつかない", (r["id"],), tuple(v for t in SIDE_VARS.values() for v in t)))
            continue
        side = side_of[bid]
        route = inv.bad_debt_route(r, business_scale=side == "biz" or (side == "rental" and rent_is_business))
        amount = int(r["amounts"]["amount"])
        if route == "51-2" and on_year == ctx.year:
            s.exp[side] += amount  # 所法51②・所令141：損失の生じた日の年分の必要経費
            s.brk.add_exp(side, "bad_debt", amount)
        elif route == "51-4" and on_year == ctx.year:
            loss = min(amount, max(0, s.rev[side] - s.exp[side] - s.dep[side]))  # 所法51④：その所得の金額を限度
            s.exp[side] += loss
            s.brk.add_exp(side, "bad_debt", loss)
        elif route == "64-1":
            if ry is None:
                if on_year == ctx.year:
                    s.problems.append((inv.BAD_DEBT_YEAR_REASON, (r["id"],), tuple(SIDE_VARS[side])))
                continue
            if ry != ctx.year:
                continue  # 収入金額を算入した年分の計算でなかったものとみなす（その年分の評価で当てる）
            deemed.setdefault(side, []).append(r)
        else:
            continue
        s.ids[side].add(r["id"])
        s.st[side] |= _states([r])
    carry = any(
        it.get("item") in _CARRY_ITEMS and it.get("amount", 0)
        for f in ctx.records("filed_document") if f["roles"].get("filer") == pid
        for it in f["attributes"].get("reported_amounts", [])
    )  # fmt: skip
    for side, rs in sorted(deemed.items()):
        total = sum(int(r["amounts"]["amount"]) for r in rs)
        income = s.rev[side] - s.exp[side] - s.dep[side]
        amt = inv.deemed_uncollectible(total, income)  # 所令180②二（赤字なら0）
        others_loss = any(s.rev[o] - s.exp[o] - s.dep[o] < 0 for o in SIDES if o != side)
        if amt and (others_loss or carry):
            s.problems.append((inv.BAD_DEBT_CAP_REASON, tuple(r["id"] for r in rs), tuple(SIDE_VARS[side])))
            continue
        s.exp[side] += amt
        s.brk.add_exp(side, "bad_debt", amt)
        s.ids[side] |= {r["id"] for r in rs}
        s.st[side] |= _states(rs)


FAMILY_USE_TARGET_REASON = (
    "家族の使用の割合（判断.按分の割合 の family_use_share）が、その人の業務の資産（depreciable_asset）・支出（business_expense）を"
    "record_ids で指していない"
)
FAMILY_USE_DUPLICATE_REASON = "同じ資産・支出に家族の使用の割合（family_use_share）の判断が複数ある"
FAMILY_USE_SUM_REASON = "同じ資産・支出の業務の割合と家族の使用の割合（family_use_share）の合計が1を超える"


def _ratio_of(j: Mapping[str, Any]) -> Fraction:
    r = j["value"]["ratio"]
    return Fraction(r["num"], r["den"])


def _family_use_check(ctx: YearContext, j: Mapping[str, Any], s: _Sides, both: tuple[str, ...]) -> None:
    """家族の使用の割合（family_use_share。語彙の約束：packages/ir の vocabulary.py の 判断.按分の割合）の入力の検査（c-入力）。
    値は _share_for_asset・_expense_amount が業務の割合（1−割合）として使う。"""
    pid = j["subject"]["person"]
    ids = j["subject"].get("record_ids") or []
    own = {a["id"] for a in ctx.records("depreciable_asset") if a["roles"]["owner"] == pid}
    own |= {e["id"] for e in ctx.records("business_expense") if e["roles"]["payer"] == pid}
    if not ids or any(rid not in own for rid in ids):
        s.problems.append((FAMILY_USE_TARGET_REASON, (j["id"],), both))
        return
    others = [
        o for o in ctx.judgments(K_SHARE)
        if o["id"] != j["id"] and o["subject"]["person"] == pid and overlaps_year(o.get("when"), ctx.year)
        and set(o["subject"].get("record_ids") or []) & set(ids)
    ]
    if any(o["value"]["purpose"] == "family_use_share" for o in others):
        s.problems.append((FAMILY_USE_DUPLICATE_REASON, (j["id"],), both))
        return
    for o in others:
        if o["value"]["purpose"] in ("asset_business_share", "household_expense_business_share") and _ratio_of(o) + _ratio_of(j) > 1:
            s.problems.append((FAMILY_USE_SUM_REASON, (j["id"], o["id"]), both))


def _business_person_checks(
    ctx: YearContext, pid: str, s: _Sides, both: tuple[str, ...]
) -> None:
    cash = [
        r["id"]
        for r in ctx.records("bookkeeping_status")
        if r["roles"]["person"] == pid
        and r["when"]["tax_year"] == ctx.year
        and (
            r["attributes"]["bookkeeping_method"] == "cash_basis_simplified"
            or r["attributes"].get("cash_basis_notice")
            or r["attributes"].get("misc_cash_basis_entry")
        )
    ]
    if cash:
        s.problems.append(("現金主義の記帳・届出・記載がある（現金主義は後の段：D21 R3）", tuple(cash), both))
    # 償却の方法の届出（定率法など）は assets.py が資産ごとに読む（method_candidates・選択.減価償却 の depreciation_method）
    for j in ctx.judgments(K_SHARE):
        if j["subject"]["person"] != pid or not overlaps_year(j.get("when"), ctx.year):
            continue
        if j["value"]["purpose"] == "family_use_share":
            _family_use_check(ctx, j, s, both)
        if j["value"]["purpose"] == "household_expense_business_share" and not j["subject"].get("record_ids"):
            s.problems.append(("家事関連費の按分の判断が対象の支出（record_ids）を指していない", (j["id"],), both))


# ---------------------------------------------------------------------------
# 青色申告の承認・青色申告特別控除の要件
# ---------------------------------------------------------------------------


def _next_business_day(d: _dt.date) -> _dt.date:
    """期限が土曜日・日曜日なら翌月曜日（aoiro §1.2「提出期限が土・日曜日・祝日等に当たる場合は、これらの日の翌日が期限」）。

    祝日の表はこのモジュールにない。祝日の翌日に出した申請は期限の後として扱い、呼び出し側で対象外になる（黙って承認にしない）。
    """
    while d.weekday() >= 5:
        d += _dt.timedelta(days=1)
    return d


def _succession_deadline(start: _dt.date) -> _dt.date:
    """相続で青色の被相続人の業務を承継した相続人の申請の期限（所基通144−1、手続の案内 A1-8・TA2070：死亡の日が1月1日〜8月31日なら
    死亡の日から4か月以内、9月1日〜10月31日はその年の12月31日、11月1日〜12月31日は翌年2月15日）。相続の開始の日を業務の開始の日（business_start_on）と読む。"""
    if start.month <= 8:
        return _add_months(start, 4)
    if start.month <= 10:
        return _dt.date(start.year, 12, 31)
    return _dt.date(start.year + 1, 2, 15)


def blue_state(
    ctx: YearContext, pid: str, year: int | None = None, splits: list[Split] | None = None
) -> tuple[str | None, tuple[str, ...], str | None]:
    """その年分（year を渡せばその年分）の青色申告の承認の状態（承認・承認なし）。決まらなければ (None, 記録, 理由)。

    読みが分かれる申請（期限の後の申請〔どの年分からの承認になるかの一次情報がない〕、相続による承継で被相続人が青色かの記録がない）は、
    その申請を数えた場合と数えない場合の両方で状態を求め、違えば splits に分かれ目を足して、数えない場合の状態を返す（D21 R6・D22 S1）。
    """
    target = ctx.year if year is None else year
    procs = sorted(
        (r for r in ctx.records("blue_return_procedure") if r["roles"]["person"] == pid),
        key=lambda r: (r["when"]["on"], r["id"]),
    )
    ids = tuple(r["id"] for r in procs)
    if not procs:
        return BLUE_NOT_APPROVED, ids, None
    events: list[tuple[int, str, int, str]] = []  # (年分, 日付, +1 承認 / −1 終わり, ID)
    maybe: list[tuple[tuple[int, str, int, str], Split]] = []  # 読みで数えるかが分かれる承認
    rejected = {r["attributes"].get("first_tax_year") for r in procs if r["attributes"]["procedure"] == "rejection_notice"}
    noticed = {r["attributes"].get("first_tax_year") for r in procs if r["attributes"]["procedure"] == "approval_notice"}
    for r in procs:
        a = r["attributes"]
        p = a["procedure"]
        on = _date(r["when"]["on"])
        if p == "approval_notice":
            if "first_tax_year" not in a:
                return None, ids, "承認の通知に最初の年分（first_tax_year）がない"
            events.append((a["first_tax_year"], r["when"]["on"], 1, r["id"]))
        elif p == "application_filed":
            fy = a.get("first_tax_year")
            if fy is None:
                return None, ids, "青色申告の申請に最初の年分（first_tax_year）がない"
            if fy in rejected or fy in noticed:
                continue
            start = _date(a["business_start_on"]) if a.get("business_start_on") else None
            deadline = _dt.date(fy, 3, 15)
            if start is not None and start >= _dt.date(fy, 1, 16):
                deadline = max(deadline, _add_months(start, 2))
            ok_general = on <= _next_business_day(deadline)
            ev = (fy, r["when"]["on"], 1, r["id"])  # 所法147：みなし承認
            if a.get("succession_by_inheritance"):
                if start is None:
                    return None, ids, "相続による業務の承継の申請に、相続の開始の日（business_start_on）がない（所基通144−1 の期限が決まらない）"
                ok_inherit = on <= _next_business_day(max(deadline, _succession_deadline(start)))
                decedent_blue = a.get("decedent_blue_approved")  # 2026-11-12 の語彙
                if ok_general and ok_inherit:
                    events.append(ev)
                elif ok_inherit and decedent_blue is True:
                    events.append(ev)  # 所基通144−1 の期限内
                elif ok_inherit and decedent_blue is False:
                    maybe.append((ev, _late_split(pid, r["id"])))  # 所法144 の期限の後
                elif ok_inherit:
                    maybe.append((ev, undetermined(
                        f"事実:被相続人の青色申告の承認:{r['id']}", Means.FACT,
                        {"person": pid, "record_id": r["id"], "入力": "相続で承継した業務の被相続人が青色申告の承認を受けていたか（所基通144−1。blue_return_procedure.attributes.decedent_blue_approved を書けば決まる）"},
                        ("承認を受けていた（所基通144−1 の期限）", "受けていなかった（所法144 の期限）"),
                    )))
                else:
                    maybe.append((ev, _late_split(pid, r["id"])))
                continue
            if ok_general:
                events.append(ev)
            else:
                maybe.append((ev, _late_split(pid, r["id"])))
        elif p == "revocation_notice":
            if "revoked_from_tax_year" not in a:
                return None, ids, "承認の取消しの通知に取り消す年分（revoked_from_tax_year）がない"
            events.append((a["revoked_from_tax_year"], r["when"]["on"], -1, r["id"]))
        elif p == "withdrawal_notice":
            if "first_tax_year" not in a:
                return None, ids, "取りやめの届出に、やめる年分（first_tax_year）がない"
            events.append((a["first_tax_year"], r["when"]["on"], -1, r["id"]))
        elif p == "business_transfer_or_closure":
            events.append((on.year + 1, r["when"]["on"], -1, r["id"]))

    def fold(evs: list[tuple[int, str, int, str]]) -> str:
        state = BLUE_NOT_APPROVED
        for y, _, sign, _ in sorted(evs):
            if y > target:
                break
            state = BLUE_APPROVED if sign > 0 else BLUE_NOT_APPROVED
        return state

    state = fold(events)
    for ev, split in maybe:
        if fold(events + [ev]) != state and splits is not None and split.id not in {x.id for x in splits}:
            splits.append(split)
    return state, ids, None


def _late_split(pid: str, rid: str) -> Split:
    return undetermined(
        f"一次情報:期限後の青色申告の申請:{rid}",
        Means.PRIMARY_SOURCE,
        {"person": pid, "record_id": rid, "事項": "所法144 の期限（土日の翌日の扱いは含む。祝日の表はない）の後に出した青色申告の申請がどの年分からの承認になるか（docs に一次情報がない）"},
        ("申請の年分から承認", "申請の年分は承認なし"),
    )


def _blue(ctx: YearContext, out: ModuleInputs) -> None:
    bids_of = _person_bids(ctx)
    rentals = _rental_bids(ctx)
    plan_people = set(_plan_people(ctx))
    for pid in ctx.persons:
        splits: list[Split] = []
        state, ids, why = blue_state(ctx, pid, splits=splits)
        procs = [r for r in ctx.records("blue_return_procedure") if r["roles"]["person"] == pid]
        st = _states(procs)
        if state is None:
            out.exclude(pid, _reason(f"青色申告の承認の年分が決まらない：{why}", ids), V_BLUE)
            state = BLUE_NOT_APPROVED
        out.set(V_BLUE, pid, state, ids, st, missing=splits)
        # 正規の簿記・申告の要件（承認がありうる人の事業だけ。ほかは要件なし）
        book_ok = False
        book_ids: list[str] = []
        book_states: set[State] = set()
        filing = FILING_OTHER
        f_miss: tuple[Split, ...] = ()
        f_ids: list[str] = []
        f_states: set[State] = set()
        if pid in plan_people:
            rent_scale = ctx.decision(K_RENT_SCALE, pid) if _has_rental(ctx, pid) else None
            is_business = False
            book_ok = True
            for bid in bids_of.get(pid, []):
                if bid in rentals.get(pid, ()):
                    business_scale = bool(rent_scale.value) if rent_scale is not None else False
                else:
                    business_scale = bool(ctx.decision(K_JIGYO, f"{pid}:{bid}").value)
                if not business_scale:
                    continue  # 業務に係る雑所得・事業的規模でない不動産所得は 55万円・65万円の要件に関係しない（措法25の2③「事業を営む」）
                is_business = True
                if _simplified_books(ctx, pid, bid):
                    book_ok = False
                    continue
                d = ctx.decision(K_BOOK, f"{pid}:{bid}")
                book_ids += list(d.record_ids)
                book_states |= set(d.states)
                book_ok = book_ok and bool(d.value)
            if rent_scale is not None and rent_scale.value and not rentals.get(pid):
                is_business = True  # 事業的規模の不動産の貸付けだが、不動産の業務の記録（business）がない：簿記の判断の1か所がない
                book_ok = False
            book_ok = book_ok and is_business
            pd = ctx.decision(K_PLAN, pid)
            f_ids = list(pd.record_ids)
            f_states = set(pd.states)
            v = pd.value
            if not isinstance(v, Mapping) or "within_deadline" not in v or "statements_attached" not in v or "method" not in v:
                out.exclude(pid, _reason("計画.申告の方法と時期に、方法・期限内か・書類の添付の欄がない", f_ids), V_FILING)
            elif v["within_deadline"] and v["statements_attached"]:
                filing = FILING_ETAX if v["method"] == "e_tax" else FILING_PAPER
            ebooks = [
                r["id"]
                for r in ctx.records("bookkeeping_status")
                if r["roles"]["person"] == pid and r["when"]["tax_year"] == ctx.year and r["attributes"].get("electronic_books_notice") == "filed"
            ]
            qualified = {
                r["attributes"].get("electronic_books_qualified")
                for r in ctx.records("bookkeeping_status")
                if r["id"] in ebooks
            }
            if ebooks and filing == FILING_PAPER and qualified == {True}:
                filing = FILING_EBOOKS  # 措法25の2④一（bookkeeping_status.attributes.electronic_books_qualified。2026-11-12 の語彙）
            elif ebooks and filing == FILING_PAPER and None in qualified:
                # 措法25の2④一：仕訳帳・総勘定元帳を優良な電子帳簿（電帳規5⑤の要件）で備え付け・保存し、届出をしていれば書面の申告でも65万円
                # （aoiro §2.5、TA2072）。要件を満たすかの記載がない：65万円（e-Tax と同じ）と55万円の両方で値が分かれれば未確定（c-入力）
                f_miss = (undetermined(
                    f"事実:優良な電子帳簿の要件:{pid}:{ctx.year}", Means.FACT,
                    {"person": pid, "record_ids": ebooks, "入力": "仕訳帳・総勘定元帳が電子帳簿保存法施行規則第5条第5項の要件を満たし最初の記録段階から電磁的記録で備え付けられているか（措規9の6。bookkeeping_status.attributes.electronic_books_qualified を書けば決まる）"},
                    ("要件を満たす（65万円）", "満たさない（55万円）"),
                ),)
        out.set(V_BOOK, pid, book_ok, book_ids, book_states)
        out.set(V_FILING, pid, filing, f_ids, f_states, missing=f_miss)


# ---------------------------------------------------------------------------
# 配当・上場株式等の譲渡
# ---------------------------------------------------------------------------

LISTED_CLASSES = ("listed_stock", "listed_investment_trust")
DIVIDEND_SCOPE_REASON = (
    "種類の決まらない配当等がある（security_class が other のもの：上場株式等・非上場株式・公社債のどれかを書く。源泉徴収選択口座の配当で"
    "特定口座年間取引報告書の配当の記載がないもの：年間取引報告書の dividends_received を書く）"
)
SIMPLE_ACCOUNT_DIVIDEND_REASON = (
    "源泉徴収を選ばない特定口座（簡易申告口座）の年間取引報告書に配当等の記載がある（特定口座に受け入れる配当等は源泉徴収選択口座内配当等"
    "〔措法37の11の6〕だけ：docs/public-sources/20261109_round2b_kabu-law-and-nta.md §5.1）。一般の口座の配当等（dividend の記録）として書く"
)
SALE_SCOPE_REASON = (
    "この版で扱わない譲渡がある（上場株式等以外の譲渡〔非上場株式は後の段：D21 R3〕、源泉徴収選択口座の譲渡を一般の譲渡の記録に書いたもの"
    "〔年間取引報告書と重複しうる〕、取得価額の記録がない譲渡）"
)
BROKERAGE_AMOUNT_REASON = "特定口座の年間取引報告書に、差引の損益（net_gain_loss）か譲渡の対価と取得費の両方がない"
MIXED_CHOICE_REASON = "同じ配当等（人の選択か、subject.record_id の1回の支払）に食い違う申告の選択が2つ以上ある"
MIXED_TAXATION_REASON = "総合課税と申告分離課税の両方の選択がある（措法8の4②：同じ年の特定上場株式等の配当等は総合課税か申告分離課税のどちらかにそろう）"
LARGE_SMALL_REASON = "大口株主等の配当（1回の金額が10万円以下）の配当計算期間（dividend の attributes.calculation_period。措法8の5①一・③の月数の材料）"


def dividend_period_months(start: _dt.date, end: _dt.date) -> int:
    """配当計算期間の月数（措法8の5③：暦に従い、1月未満の端数は1月、12月を超えるときは12月）。"""
    y, m, d = ymd(start, end)
    return max(1, min(12, y * 12 + m + (1 if d else 0)))
#: 措法8の5①一の「十万円」（配当計算期間の月数を乗じて12で除す前の額）
SMALL_DIVIDEND_YEN = 100_000
LOSS_DIVIDEND_REASON = "源泉徴収選択口座の譲渡損失を申告するのに同じ口座の配当等を申告不要にしている（措法37の11の6⑩：申告不要にできない）"
WITHHOLDING_MIX_REASON = "同じ源泉徴収選択口座で譲渡と配当の申告の選択が違う（年間取引報告書の源泉徴収税額の譲渡・配当等の内訳：brokerage_annual の amounts.transfer_withholding_tax・dividend_withholding_tax）"

#: 配当等の種類（dividend.attributes.distribution_type）→ 配当控除の区分（所法92①・措法9。haito §2・§3・§4）。
#: "none" は配当控除の対象外（TA1250 の列挙・所法92① の外国法人の除外）。表にない種類（other）と記載のないものは区分が決まらない。
CREDIT_CLASS = {
    "surplus_dividend": "surplus",  # 剰余金の配当・利益の配当・剰余金の分配・金銭の分配（所法92①一イ）
    "specified_stock_investment_trust": "surplus",  # 特定株式投資信託の収益の分配は剰余金の配当等に含める（TA1250）
    "securities_investment_trust": "trust",  # 証券投資信託の収益の分配（所法92①一ロ）
    "foreign_currency_securities_investment_trust": "fx_trust",  # 一般外貨建等証券投資信託（率は半分：措法9、TA1250）
    "foreign_index_linked_specified_stock_investment_trust": "none",
    "specified_foreign_currency_securities_investment_trust": "none",
    "qualified_institutional_private_placement_trust": "none",
    "private_placement_bond_investment_trust": "none",
    "investment_corporation": "none",
    "specific_purpose_company": "none",
    "specific_purpose_trust": "none",
    "fund_interest": "none",
    "foreign_corporation": "none",  # 外国法人から受ける配当等（所法92①かっこ書き）
}
CREDIT_VARS = {"surplus": V_CREDIT_SURPLUS, "trust": V_CREDIT_TRUST, "fx_trust": V_CREDIT_FX_TRUST}
CREDIT_UNKNOWN_REASON = (
    "総合課税の配当等に、配当等の種類（distribution_type）の記載がないか「その他」のものがある（配当控除の対象か・率の区分が決まらない："
    "所法92①・措法9）"
)
CREDIT_BROKERAGE_REASON = (
    "総合課税を選んだ源泉徴収選択口座の配当等（年間取引報告書の額）の種類の内訳が、同じ口座の配当等の記録（distribution_type つき）から確かめられない"
)
CREDIT_INTEREST_REASON = (
    "総合課税の配当等に配当控除の区分の違うものがあり、負債の利子（所法24②）をどの区分の配当所得から控除するかを決める一次情報が docs にない"
    "（所基通24−5(1) はほかの株式等の配当等からも控除できるとだけ書く）"
)


def credit_amounts(parts: list[tuple[str, int]], interest: int) -> dict[str, int] | None:
    """配当控除の区分ごとの配当所得の金額（総合課税。損益通算の前）。parts は (区分, 収入金額) の並び。

    負債の利子は、区分が1つ（対象外の区分を含めて）なら、その区分の収入金額から控除する（赤字は0：手引き 3-2_05）。
    区分が2つ以上で負債の利子があるときは、控除の当て方の候補（credit_amount_candidates）が全部同じ値なら その値、違えば None。
    """
    cands = credit_amount_candidates(parts, interest)
    return cands[0] if all(c == cands[0] for c in cands) else None


def credit_amount_candidates(parts: list[tuple[str, int]], interest: int) -> list[dict[str, int]]:
    """負債の利子を区分に当てる読みの候補ごとの区分の金額（仮説 H3：docs/hypotheses/20261111_impl-research3_all-model.md）。

    (a) 元本に結びつける・(c) 納税者が選ぶ：区分の順の全部（ある区分から先に控除し、控除しきれない額を次の区分から：所基通24−5(1)）。
    (b) 収入金額の比で按分する（1円未満は切り捨てた額と切り上げた額の両方を候補にする）。区分が1つなら候補は1つ。
    """
    import itertools

    totals: dict[str, int] = {}
    for cls, amount in parts:
        if amount:
            totals[cls] = totals.get(cls, 0) + amount
    keys = sorted(totals)

    def to_out(rest: Mapping[str, Any]) -> dict[str, int]:
        out = {k: 0 for k in CREDIT_VARS}
        for cls, v in rest.items():
            if cls in out:
                out[cls] = max(0, int(v))
        return out

    if not interest or len(keys) <= 1:
        return [to_out({k: totals[k] - interest for k in keys})]
    outs: list[dict[str, int]] = []
    for order in itertools.permutations(keys):
        left, rest = interest, dict(totals)
        for k in order:
            take = min(left, rest[k])
            rest[k] -= take
            left -= take
        outs.append(to_out(rest))
    whole = sum(totals.values())
    for rnd in (lambda f: f.numerator // f.denominator, lambda f: -((-f.numerator) // f.denominator)):
        outs.append(to_out({k: max(0, totals[k] - rnd(Fraction(interest * totals[k], whole))) for k in keys}))
    return outs


DIVIDEND_CANDIDATES = (
    Candidate({"target": "dividend", "declare": False}, "申告不要"),
    Candidate({"target": "dividend", "declare": True, "taxation": "aggregate"}, "総合課税"),
    Candidate({"target": "dividend", "declare": True, "taxation": "separate"}, "申告分離課税"),
)
TRANSFER_CANDIDATES = (
    Candidate({"target": "withholding_account_transfer", "declare": False}, "申告不要"),
    Candidate({"target": "withholding_account_transfer", "declare": True}, "申告する"),
)


def _taxable_dividends(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    """その年分の配当等のうち、非課税（NISA：措法9の8）を除いたもの。"""
    return sorted(
        (
            r
            for r in ctx.records("dividend")
            if r["roles"]["recipient"] == pid and _year_of(r) == ctx.year and r["attributes"]["account_type"] != "nisa"
        ),
        key=lambda r: r["id"],
    )


def _brokerage(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    return sorted((r for r in ctx.records("brokerage_annual") if r["roles"]["holder"] == pid and r["when"]["tax_year"] == ctx.year), key=lambda r: r["id"])


def _in_scope_dividend(r: Mapping[str, Any]) -> bool:
    """個人の選択で区分する配当（上場株式等で、一般の口座のもの）。"""
    return r["attributes"]["security_class"] in LISTED_CLASSES and r["attributes"]["account_type"] == "other_account"


def _unlisted(r: Mapping[str, Any]) -> bool:
    """上場株式等以外の株式（非上場株式）の配当で、一般の口座のもの（総合課税。少額配当は申告不要を選べる：措法8の5①一）。"""
    return r["attributes"]["security_class"] == "unlisted_stock" and r["attributes"]["account_type"] == "other_account"


def _bond(r: Mapping[str, Any]) -> bool:
    """公社債（security_class public_bond。国債・地方債・公募公社債などの特定公社債と読む：措法37の11②、kabu §4）の利子で一般の口座のもの。"""
    return r["attributes"]["security_class"] == "public_bond" and r["attributes"]["account_type"] == "other_account"


def _is_withholding_account_dividend(r: Mapping[str, Any]) -> bool:
    return r["attributes"]["security_class"] in LISTED_CLASSES and r["attributes"]["account_type"] == "withholding_specified_account"


def _large_slots(ctx: YearContext) -> list[DecisionSlot]:
    """判断.大口株主等（配当の支払ごと）：一般の口座の上場株式等の配当の1か所。未入力なら単調の群で両端を評価する（2026-11-11）。"""
    out = []
    for pid in ctx.persons:
        for r in _taxable_dividends(ctx, pid):
            if not _in_scope_dividend(r):
                continue
            rid = r["id"]
            out.append(
                DecisionSlot(
                    key=rid,
                    target={"dividend_id": rid},
                    matches=lambda rec, rid=rid: rec["subject"]["dividend_id"] == rid,
                    persons=(pid,),
                    monotone=f"大口株主等:{pid}",
                )
            )
    return out


def _stock_slots(ctx: YearContext) -> list[DecisionSlot]:
    out = []
    for pid in ctx.persons:
        if any(_in_scope_dividend(r) or _unlisted(r) or _bond(r) for r in _taxable_dividends(ctx, pid)):
            out.append(
                DecisionSlot(
                    key=f"{pid}:配当",
                    target={"person": pid, "target": "dividend", "tax_year": ctx.year},
                    matches=lambda rec, pid=pid: rec["subject"]["person"] == pid
                    and rec["value"]["target"] == "dividend"
                    and rec["subject"].get("account_id") is None
                    and rec["subject"].get("record_id") is None,
                    candidates=DIVIDEND_CANDIDATES,
                )
            )
        for rec in _brokerage(ctx, pid):
            acc = rec["attributes"]["account_id"]
            if rec["attributes"]["withholding_elected"]:
                out.append(
                    DecisionSlot(
                        key=f"{pid}:{acc}",
                        target={"person": pid, "account_id": acc, "target": "withholding_account_transfer", "tax_year": ctx.year},
                        matches=lambda r, pid=pid, acc=acc: r["subject"]["person"] == pid
                        and r["subject"].get("account_id") == acc
                        and r["value"]["target"] == "withholding_account_transfer",
                        candidates=TRANSFER_CANDIDATES,
                    )
                )
                if rec["amounts"].get("dividends_received", 0) > 0:
                    out.append(
                        DecisionSlot(
                            key=f"{pid}:配当:{acc}",
                            target={"person": pid, "account_id": acc, "target": "dividend", "tax_year": ctx.year},
                            matches=lambda r, pid=pid, acc=acc: r["subject"]["person"] == pid
                            and r["subject"].get("account_id") == acc
                            and r["value"]["target"] == "dividend",
                            candidates=DIVIDEND_CANDIDATES,
                        )
                    )
    return out


def _dividend_interest(ctx: YearContext, pid: str, total_declared: int) -> tuple[int, tuple[str, ...], set[State], Split | None]:
    """負債の利子（所法24②、所令59②③）：費目が配当の負債の利子の支出（業務の識別子なし）の合計 × 保有の月数/12。

    保有の月数は負債（loan：purpose_asset_id のない借入れ）の期間とその年の重なり（1月未満は1月）。負債の記録がなければ通年（12月）と読む（基通24−10：月数按分は年の中途の取得・譲渡のときだけ）。
    負債の記録が2つ以上あれば、どの配当の負債か決まらないので対象外。
    """
    recs = sorted(
        (
            r
            for r in ctx.records("business_expense")
            if r["roles"]["payer"] == pid
            and _on_year(r) == ctx.year
            and r["attributes"].get("expense_category") in DIVIDEND_INTEREST_CATEGORIES
            and not r["attributes"].get("business_id")
        ),
        key=lambda r: r["id"],
    )
    if not recs or total_declared <= 0:
        return 0, (), set(), None
    ids = tuple(r["id"] for r in recs)
    st = _states(recs)
    # 支出に借入れ（business_expense の loan_id。2026-11-12）が書いてあれば、その借入れの保有の月数で支出ごとに按分する（IK-89）
    by_id = {r["id"]: r for r in ctx.records("loan")}
    linked = [r for r in recs if r["attributes"].get("loan_id") in by_id]
    if linked:
        part = sum((Fraction(r["amounts"]["amount"] * _loan_months(by_id[r["attributes"]["loan_id"]], ctx.year), 12) for r in linked), Fraction(0))
        ids = (*ids, *sorted({r["attributes"]["loan_id"] for r in linked}))
        recs = [r for r in recs if r not in linked]
        if not recs:
            amount = int(part) if part.denominator == 1 else ctx.round_unfounded(ROUNDING_EXPENSE, part)
            return amount, ids, st, None
        rest_amount, rest_ids, _, rest_miss = _dividend_interest_unlinked(ctx, pid, recs)
        total = part + rest_amount
        amount = int(total) if total.denominator == 1 else ctx.round_unfounded(ROUNDING_EXPENSE, total)
        return amount, tuple(dict.fromkeys((*ids, *rest_ids))), st, rest_miss
    amount, ids2, _, miss = _dividend_interest_unlinked(ctx, pid, recs)
    total = amount
    return (int(total) if total.denominator == 1 else ctx.round_unfounded(ROUNDING_EXPENSE, total)), tuple(dict.fromkeys((*ids, *ids2))), st, miss


def _dividend_interest_unlinked(ctx: YearContext, pid: str, recs: list[Mapping[str, Any]]) -> tuple[Fraction, tuple[str, ...], set[State], Split | None]:
    """借入れに結びつけていない配当の負債の利子の支出：負債の記録の保有の月数で按分（丸める前の額）。"""
    ids = tuple(r["id"] for r in recs)
    st = _states(recs)
    interest = sum(r["amounts"]["amount"] for r in recs)
    loans = [r for r in ctx.records("loan") if r["roles"]["borrower"] == pid and not r["attributes"].get("purpose_asset_id") and overlaps_year(r.get("when"), ctx.year)]
    if not loans:
        return Fraction(interest), ids, st, None
    ids = (*ids, *(r["id"] for r in loans))
    months = sorted({_loan_months(r, ctx.year) for r in loans})
    if len(months) > 1:
        # 負債が2つ以上で保有の月数が違う：どの利子がどの負債のものかで按分（所令59②③）の額が変わる（D21 R6）。支出の loan_id を書けば決まる
        miss = undetermined(
            f"事実:配当の負債の利子の負債:{pid}:{ctx.year}",
            Means.FACT,
            {"person": pid, "expense_ids": [r["id"] for r in recs], "loan_ids": [r["id"] for r in loans],
             "入力": "配当の負債の利子の支出（business_expense の dividend_debt_interest）がどの借入れ（loan）の利子か（business_expense の attributes.loan_id）"},
            tuple(f"保有の月数 {m}" for m in months),
        )
        months = months[-1:]
    else:
        miss = None
    return Fraction(interest * months[0], 12), ids, st, miss


def _loan_months(loan: Mapping[str, Any], year: int) -> int:
    start = max(_date(loan["when"]["from_on"]), _dt.date(year, 1, 1))
    end = min(_date(loan["when"]["to_on"]) if loan["when"].get("to_on") else _dt.date(year, 12, 31), _dt.date(year, 12, 31))
    return calendar_months(start, end)


def _stock(ctx: YearContext, out: ModuleInputs) -> None:
    # 第二表の住民税の欄の材料（2026-11-12 の4回目。IK-111）：申告不要を選んだ非上場株式の少額配当等（G29）・申告する配当等の配当割額（G30）・
    # 申告する源泉徴収選択口座の譲渡の株式等譲渡所得割額（G35）。対象外の理由は配当・譲渡の値と同じ
    dividend_vars = (V_DIV_AGG, V_DIV_SEP, V_DIV_AGG_INT, V_DIV_SEP_INT, V_DIV_WITHHOLD, V_SMALL_UNLISTED, V_DIV_LOCAL)
    sale_vars = (V_SALE_REV, V_SALE_COST, V_SALE_WITHHOLD, V_SALE_LOCAL)
    for pid in ctx.persons:
        small_unlisted = div_local = sale_local = 0
        divs = _taxable_dividends(ctx, pid)
        scope_out = [r["id"] for r in divs if not _in_scope_dividend(r) and not _is_withholding_account_dividend(r) and not _unlisted(r) and not _bond(r)]
        ok_divs = [r for r in divs if _in_scope_dividend(r) or _unlisted(r) or _bond(r)]
        brokerage = _brokerage(ctx, pid)
        withheld_divs = [r for r in divs if _is_withholding_account_dividend(r)]
        has_annual_div = any(r["attributes"]["withholding_elected"] and r["amounts"].get("dividends_received", 0) > 0 for r in brokerage)
        if withheld_divs and not has_annual_div:
            scope_out += [r["id"] for r in withheld_divs]
        excluded_div = False
        if scope_out:
            for v in dividend_vars:
                out.exclude(pid, _reason(DIVIDEND_SCOPE_REASON, scope_out), v)
            excluded_div = True
        simple_div = [r["id"] for r in brokerage if not r["attributes"]["withholding_elected"] and r["amounts"].get("dividends_received", 0) > 0]
        if simple_div:
            for v in dividend_vars:
                out.exclude(pid, _reason(SIMPLE_ACCOUNT_DIVIDEND_REASON, simple_div), v)
            excluded_div = True
        total_div = sum(r["amounts"]["gross"] for r in ok_divs)
        _check_amount(total_div, "配当等の収入金額")
        agg = sep = 0
        d_ids: list[str] = [r["id"] for r in divs]
        d_states: set[State] = _states(divs)
        withhold = 0
        withhold_ids: list[str] = []
        withhold_missing: list[str] = []
        modes: set[str] = set()  # 申告した課税方式（aggregate・separate）
        small_miss: list[Split] = []
        agg_parts: list[tuple[Mapping[str, Any], int]] = []  # 総合課税の一般の口座の配当等（記録, 収入金額）
        agg_accounts: list[Mapping[str, Any]] = []  # 総合課税を選んだ源泉徴収選択口座の年間取引報告書
        if ok_divs:
            d = ctx.decision(K_STOCK, f"{pid}:配当")
            d_ids += list(d.record_ids)
            d_states |= set(d.states)
            value = d.value
            matched = [
                c
                for c in ctx.choices(K_STOCK)
                if c["subject"]["person"] == pid
                and c["value"]["target"] == "dividend"
                and c["subject"].get("account_id") is None
                and c["subject"].get("record_id") is None
                and overlaps_year(c.get("when"), ctx.year)
            ]
            if len({(c["value"].get("declare"), c["value"].get("taxation")) for c in matched}) > 1:
                for w in dividend_vars:
                    out.exclude(pid, _reason(MIXED_CHOICE_REASON, [c["id"] for c in matched]), w)
                excluded_div = True
            # 1回に支払を受ける配当等ごとの選択（措法8の5④）：subject.record_id のある選択はその支払にだけ当て、ないものは人の選択（上の d）
            per_payment: dict[str, list[Mapping[str, Any]]] = {}
            for c in ctx.choices(K_STOCK):
                if c["subject"]["person"] == pid and c["value"]["target"] == "dividend" and c["subject"].get("record_id") and overlaps_year(c.get("when"), ctx.year):
                    per_payment.setdefault(c["subject"]["record_id"], []).append(c)
            for r in ok_divs:
                pc = per_payment.get(r["id"], [])
                if len({(c["value"].get("declare"), c["value"].get("taxation")) for c in pc}) > 1:
                    for w in dividend_vars:
                        out.exclude(pid, _reason(MIXED_CHOICE_REASON, [c["id"] for c in pc]), w)
                    excluded_div = True
                rv = pc[0]["value"] if pc else value
                if pc:
                    d_ids += [c["id"] for c in pc]
                    d_states |= _states(pc)
                declared = bool(rv.get("declare"))
                taxation = rv.get("taxation")
                if declared and taxation not in ("aggregate", "separate") and not _unlisted(r) and not _bond(r):
                    for w in dividend_vars:
                        out.exclude(pid, _reason("配当等を申告するとした選択に課税方式（taxation）がない", [c["id"] for c in pc] or d.record_ids), w)
                    excluded_div = True
                if _bond(r):
                    # 特定公社債の利子（措法8の4①六）：申告すれば申告分離課税（総合課税は選べない：kabu §1.2 の手引き）、しなければ申告不要（措法8の5①七）。
                    # 措法8の4② の課税方式のそろえ（特定上場株式等の配当等）の対象外なので modes に入れない
                    if declared:
                        sep += r["amounts"]["gross"]
                        withhold, withhold_missing = _add_withhold(r, withhold, withhold_missing, withhold_ids)
                    continue
                unlisted = _unlisted(r)
                if not unlisted:
                    ld = ctx.decision(K_LARGE_HOLDER, r["id"])
                    d_ids += list(ld.record_ids)
                    d_states |= set(ld.states)
                gross = r["amounts"]["gross"]
                if unlisted or ld.value:
                    # 大口株主等（措法8の4①一）・上場株式等以外の株式の配当：措法8の4 の申告分離課税の対象外で総合課税（所法22・24）。
                    # 内国法人からの少額配当は申告不要を選べる（措法8の5①一。外国法人からの配当は第1号に当たらない）
                    domestic = r["attributes"].get("distribution_type") != "foreign_corporation"
                    if not declared and gross <= SMALL_DIVIDEND_YEN and domestic:
                        # 少額配当（措法8の5①一・③：1回の額が 10万円×配当計算期間の月数/12 以下なら申告不要を選べる）。月数は dividend の
                        # calculation_period（2026-11-12）から③で数える。ないとき：月数が1でも少額なら申告不要（数えない）。そうでなければ月数で分かれ、
                        # 額が違うので未確定（D21 R6）
                        cp = r["attributes"].get("calculation_period")
                        if cp is not None and cp.get("to_on"):
                            if gross * 12 <= SMALL_DIVIDEND_YEN * dividend_period_months(_date(cp["from_on"]), _date(cp["to_on"])):
                                small_unlisted += gross if unlisted else 0
                                continue
                        elif gross * 12 <= SMALL_DIVIDEND_YEN:
                            small_unlisted += gross if unlisted else 0
                            continue
                        else:
                            small_miss.append(undetermined(
                                f"事実:配当計算期間の月数:{r['id']}", Means.FACT,
                                {"person": pid, "record_id": r["id"], "入力": LARGE_SMALL_REASON},
                                ("少額配当（申告不要）", "少額配当でない（総合課税）"),
                            ))
                    agg += gross
                    agg_parts.append((r, gross))
                    modes.add("aggregate")
                    withhold, withhold_missing = _add_withhold(r, withhold, withhold_missing, withhold_ids)
                    div_local += int(r["amounts"].get("dividend_local_tax", 0) or 0)
                    continue
                if declared and taxation == "aggregate":
                    agg += gross
                    agg_parts.append((r, gross))
                    modes.add("aggregate")
                    withhold, withhold_missing = _add_withhold(r, withhold, withhold_missing, withhold_ids)
                    div_local += int(r["amounts"].get("dividend_local_tax", 0) or 0)
                elif declared and taxation == "separate":
                    sep += gross
                    modes.add("separate")
                    withhold, withhold_missing = _add_withhold(r, withhold, withhold_missing, withhold_ids)
                    div_local += int(r["amounts"].get("dividend_local_tax", 0) or 0)
        # 源泉徴収選択口座の配当（年間取引報告書の金額。口座ごとの選択：措法37の11の6⑨）
        for rec in brokerage:
            acc = rec["attributes"]["account_id"]
            amount = rec["amounts"].get("dividends_received", 0)
            if not rec["attributes"]["withholding_elected"] or amount <= 0:
                continue
            dd = ctx.decision(K_STOCK, f"{pid}:配当:{acc}")
            d_ids += [rec["id"], *dd.record_ids]
            d_states |= set(dd.states) | _states([rec])
            value = dd.value
            declared = bool(value.get("declare"))
            taxation = value.get("taxation")
            if declared and taxation not in ("aggregate", "separate"):
                for w in dividend_vars:
                    out.exclude(pid, _reason("配当等を申告するとした選択に課税方式（taxation）がない", dd.record_ids), w)
                excluded_div = True
                continue
            if not declared:
                continue
            if taxation == "aggregate":
                agg += amount
                agg_accounts.append(rec)
                modes.add("aggregate")
            else:
                sep += amount
                modes.add("separate")
            withhold_ids.append(rec["id"])
            div_local += int(rec["amounts"].get("dividend_local_tax", 0) or 0)
        if len(modes) > 1:
            for w in dividend_vars:
                out.exclude(pid, _reason(MIXED_TAXATION_REASON, d_ids), w)
            excluded_div = True
        interest, i_ids, i_states, i_miss = _dividend_interest(ctx, pid, agg + sep)
        d_ids += list(i_ids)
        d_states |= i_states
        int_miss = ((i_miss,) if i_miss is not None else ()) + tuple(small_miss)
        if max(agg, sep, withhold) > INT32_MAX and not excluded_div:
            for w in dividend_vars:
                out.exclude(pid, _reason("配当等の金額が判定コアの整数の範囲を超える", d_ids), w)
            excluded_div = True
        if withhold_missing:
            out.exclude(pid, _reason("申告する配当等の支払に源泉徴収税額（amounts.withholding_tax）が書かれていない（0 か未記録かを区別できない）", withhold_missing), V_DIV_WITHHOLD)
        out.set(V_DIV_AGG, pid, 0 if excluded_div else agg, d_ids, d_states, missing=tuple(small_miss))
        out.set(V_DIV_SEP, pid, 0 if excluded_div else sep, d_ids, d_states)
        # 負債の利子は申告する配当の側に当てる（総合と分離は同時にはない：MIXED_TAXATION_REASON）
        out.set(V_DIV_AGG_INT, pid, 0 if excluded_div or sep else interest, d_ids, d_states, missing=int_miss)
        out.set(V_DIV_SEP_INT, pid, 0 if excluded_div or not sep else interest, d_ids, d_states, missing=int_miss)
        out.set(V_DIV_WITHHOLD, pid, 0 if excluded_div or withhold_missing else withhold, withhold_ids, d_states)
        out.set(V_SMALL_UNLISTED, pid, 0 if excluded_div else small_unlisted, d_ids, d_states, missing=tuple(small_miss))
        out.set(V_DIV_LOCAL, pid, 0 if excluded_div else div_local, d_ids, d_states)
        _credit_classes(out, pid, agg_parts, agg_accounts, withheld_divs, interest if not sep else 0, excluded_div, d_ids, d_states, int_miss)
        # 譲渡
        sales = sorted(
            (
                r
                for r in ctx.records("security_sale")
                if r["roles"]["seller"] == pid and _year_of(r) == ctx.year and r["attributes"].get("account_type") != "nisa"
            ),
            key=lambda r: r["id"],
        )
        bad_sales = [
            r["id"]
            for r in sales
            if r["attributes"]["security_class"] not in LISTED_CLASSES
            or r["attributes"].get("account_type") == "withholding_specified_account"
            or "acquisition_cost" not in r["amounts"]
        ]
        rev = cost = 0
        s_ids = [r["id"] for r in sales]
        s_states = _states(sales)
        excluded_sale = False
        if bad_sales:
            for v2 in sale_vars:
                out.exclude(pid, _reason(SALE_SCOPE_REASON, bad_sales), v2)
            excluded_sale = True
        for r in sales:
            if r["id"] in bad_sales:
                continue
            rev += r["amounts"]["proceeds"]
            cost += r["amounts"]["acquisition_cost"] + r["amounts"].get("selling_expenses", 0)
        sale_withhold = 0
        div_extra: list[tuple[int, str]] = []  # 配当等だけを申告する源泉徴収選択口座の配当等の源泉徴収税額（内訳の欄）
        mix_miss: list[Split] = []
        sale_withhold_missing: list[str] = []
        for r in brokerage:
            a = r["amounts"]
            acc = r["attributes"]["account_id"]
            s_ids.append(r["id"])
            s_states |= _states([r])
            include = True
            if r["attributes"]["withholding_elected"]:
                d2 = ctx.decision(K_STOCK, f"{pid}:{acc}")
                s_ids += list(d2.record_ids)
                s_states |= set(d2.states)
                include = bool(d2.value.get("declare"))
                dividends = a.get("dividends_received", 0)
                mixed = False
                if dividends > 0:
                    dd = ctx.decision(K_STOCK, f"{pid}:配当:{acc}")
                    if bool(dd.value.get("declare")) != include:
                        mixed = True
                        if include and not bool(dd.value.get("declare")) and (a.get("net_gain_loss") if a.get("net_gain_loss") is not None else 0) < 0:
                            for w in dividend_vars:
                                out.exclude(pid, _reason(LOSS_DIVIDEND_REASON, [r["id"], *dd.record_ids]), w)
                if mixed and "transfer_withholding_tax" in a and "dividend_withholding_tax" in a:
                    # 年間取引報告書の源泉徴収税額の譲渡・配当等の内訳（2026-11-12。IK-93）：申告する側の分だけを当てる
                    if include:
                        sale_withhold += a["transfer_withholding_tax"]
                    else:
                        div_extra.append((a["dividend_withholding_tax"], r["id"]))
                elif mixed:
                    # 内訳の欄（transfer_withholding_tax・dividend_withholding_tax）がない。申告する側の源泉徴収税額は0〜全額の間で決まらない
                    # （額が分かれるので未確定。D21 R6）
                    mix_miss.append(undetermined(
                        f"事実:源泉徴収税額の譲渡と配当の内訳:{pid}:{acc}", Means.FACT,
                        {"person": pid, "account_id": acc, "record_ids": [r["id"], *d2.record_ids, *dd.record_ids], "入力": WITHHOLDING_MIX_REASON},
                        ("申告する側に源泉徴収税額を当てない", "源泉徴収税額の全部を当てる"),
                    ))
                    if include:
                        if "withholding_tax" in a:
                            sale_withhold += a["withholding_tax"]
                        else:
                            sale_withhold_missing.append(r["id"])
                elif include:
                    if "withholding_tax" in a:
                        sale_withhold += a["withholding_tax"]
                    else:
                        sale_withhold_missing.append(r["id"])
            if not include:
                continue
            if r["attributes"]["withholding_elected"]:
                sale_local += int(a.get("transfer_local_tax", 0) or 0)  # 申告する源泉徴収選択口座の株式等譲渡所得割額（G35）
            if "net_gain_loss" in a:
                gain = a["net_gain_loss"]
            elif "proceeds" in a and "acquisition_cost" in a:
                gain = a["proceeds"] - a["acquisition_cost"]
            else:
                for v2 in sale_vars:
                    out.exclude(pid, _reason(BROKERAGE_AMOUNT_REASON, [r["id"]]), v2)
                excluded_sale = True
                continue
            if gain >= 0:
                rev += gain
            else:
                cost += -gain
        if max(rev, cost) > INT32_MAX and not excluded_sale:
            for v2 in sale_vars:
                out.exclude(pid, _reason("上場株式等の譲渡の金額が判定コアの整数の範囲を超える", s_ids), v2)
            excluded_sale = True
        if sale_withhold_missing:
            out.exclude(pid, _reason("源泉徴収選択口座の年間取引報告書に源泉徴収税額がない（申告する口座）", sale_withhold_missing), V_SALE_WITHHOLD)
        out.set(V_SALE_REV, pid, 0 if excluded_sale else rev, s_ids, s_states)
        out.set(V_SALE_COST, pid, 0 if excluded_sale else cost, s_ids, s_states)
        out.set(V_SALE_WITHHOLD, pid, 0 if excluded_sale or sale_withhold_missing else sale_withhold, s_ids, s_states, missing=mix_miss)
        out.set(V_SALE_LOCAL, pid, 0 if excluded_sale else sale_local, s_ids, s_states)
        if div_extra:
            iv = out.values[(V_DIV_WITHHOLD, pid)]
            add = 0 if excluded_div or withhold_missing else sum(x for x, _ in div_extra)
            out.values[(V_DIV_WITHHOLD, pid)] = _dc_replace(iv, value=iv.value + add, record_ids=tuple(sorted({*iv.record_ids, *(i for _, i in div_extra)})))
        if mix_miss:
            iv = out.values[(V_DIV_WITHHOLD, pid)]
            out.values[(V_DIV_WITHHOLD, pid)] = _dc_replace(iv, missing=unique_splits((*iv.missing, *mix_miss)))


def _credit_classes(
    out: ModuleInputs,
    pid: str,
    agg_parts: list[tuple[Mapping[str, Any], int]],
    agg_accounts: list[Mapping[str, Any]],
    withheld_divs: list[Mapping[str, Any]],
    interest: int,
    excluded_div: bool,
    d_ids: list[str],
    d_states: set[State],
    interest_missing: tuple[Split, ...] = (),
) -> None:
    """配当控除の区分ごとの配当所得の金額（tax の配当控除が引く。haito §2〜§4）。区分が決まらなければ3つとも対象外。
    負債の利子の区分への当て方が候補で分かれれば未確定（missing）。"""
    parts: list[tuple[str, int]] = []
    unknown: list[str] = []
    for r, gross in agg_parts:
        cls = CREDIT_CLASS.get(r["attributes"].get("distribution_type", ""))
        if cls is None:
            unknown.append(r["id"])
        parts.append((cls or "?", gross))
    problems: list[tuple[str, list[str]]] = []
    if unknown:
        problems.append((CREDIT_UNKNOWN_REASON, unknown))
    brokerage_miss: Split | None = None
    if agg_accounts:
        # 年間取引報告書の配当等は種類の内訳を持たない。総合課税を選んだ口座の額の合計が、源泉徴収選択口座の配当等の記録（種類つき）の合計と
        # 一致し、ほかに源泉徴収選択口座の配当がない（全部の口座を総合課税にした）ときだけ、記録の種類で区分する
        total = sum(a["amounts"].get("dividends_received", 0) for a in agg_accounts)
        typed = [r for r in withheld_divs if CREDIT_CLASS.get(r["attributes"].get("distribution_type", "")) is not None]
        if len(typed) != len(withheld_divs) or sum(r["amounts"]["gross"] for r in withheld_divs) != total:
            # 種類の内訳が記録から決まらない：区分（剰余金の配当等・証券投資信託・一般外貨建等・対象外）のどれに当たるかで配当控除が分かれる
            # （D21 R6）。値は剰余金の配当等として書き、未確定にする
            parts.append(("surplus", total))
            brokerage_miss = undetermined(
                f"事実:年間取引報告書の配当等の種類:{pid}", Means.FACT,
                {"person": pid, "record_ids": [a["id"] for a in agg_accounts] + [r["id"] for r in withheld_divs], "入力": CREDIT_BROKERAGE_REASON
                 + "（同じ口座の配当等の記録 dividend に distribution_type を書き、合計を年間取引報告書の額に合わせる）"},
                tuple(sorted({*CREDIT_VARS, "none"})),
            )
        else:
            parts += [(CREDIT_CLASS[r["attributes"]["distribution_type"]], r["amounts"]["gross"]) for r in withheld_divs]
    miss = tuple(interest_missing) + ((brokerage_miss,) if brokerage_miss is not None else ())
    amounts: dict[str, int] | None = None
    if not problems:
        cands = credit_amount_candidates(parts, interest)
        amounts = cands[0]
        if any(c != cands[0] for c in cands):
            # 区分が2つ以上で負債の利子がある：どの区分から控除するかを決める一次情報がない（仮説 H3。D22 S1：候補の全部で評価して分かれた）
            miss += (
                undetermined(
                    f"一次情報:配当の負債の利子の区分への当て方:{pid}",
                    Means.PRIMARY_SOURCE,
                    {"person": pid, "record_ids": [r["id"] for r, _ in agg_parts] + [a["id"] for a in agg_accounts],
                     "事項": CREDIT_INTEREST_REASON, "決める手段": "国税庁の見解（docs/hypotheses/20261111_impl-research3_all-model.md H3）"},
                    ("元本の区分から先に控除（区分の順の全部）", "収入金額の比で按分", "納税者の選択"),
                ),
            )
    for cls, var in CREDIT_VARS.items():
        for text, ids in problems:
            out.exclude(pid, _reason(text, ids), var)
        out.set(var, pid, 0 if excluded_div or problems or amounts is None else amounts[cls], d_ids, d_states, missing=miss)


def _add_withhold(r: Mapping[str, Any], total: int, missing: list[str], ids: list[str]) -> tuple[int, list[str]]:
    if "withholding_tax" in r["amounts"]:
        ids.append(r["id"])
        return total + r["amounts"]["withholding_tax"], missing
    return total, [*missing, r["id"]]


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------


def _other_misc(ctx: YearContext, out: ModuleInputs) -> None:
    """その他の雑所得：benefit_receipt の other は所得の種類が決まらないので候補で評価する。失業給付・傷病手当金・出産手当金・奨学金・
    労災の給付（日本年金機構の非課税所得の例：nenkin §4.3）は所得に入れない。未支給年金は _windfall が一時所得に数える（TA1605）。"""
    for pid in ctx.persons:
        unknown = sorted(
            r["id"]
            for r in ctx.records("benefit_receipt")
            if r["roles"]["recipient"] == pid and r["attributes"]["benefit_type"] == "other" and overlaps_year(r.get("when"), ctx.year)
        )
        if unknown:
            # 給付の種類の語彙がなく、非課税・雑所得・一時所得（未支給年金：TA1605）のどれかが決まらない。候補で額が分かれるので未確定（D21 R6）。
            # 値は非課税の候補（その他の雑所得に数えない）のまま
            m = undetermined(
                f"事実:その他の給付の所得の区分:{pid}:{ctx.year}", Means.FACT,
                {"person": pid, "record_ids": unknown, "入力": "benefit_receipt の benefit_type「その他」の給付の種類（語彙にある種類〔未支給年金・労災の給付など〕に当たらない給付。非課税・雑所得・一時所得のどれかの一次情報が要る）"},
                ("非課税", "その他の雑所得", "一時所得"),
            )
            for v in (V_OTHER_MISC_REV, V_WF_TOTAL):
                iv = out.values[(v, pid)]
                out.values[(v, pid)] = _dc_replace(iv, missing=unique_splits((*iv.missing, m)))


def build_inputs(ctx: YearContext) -> ModuleInputs:
    # 期間対応（直所2−78）を当てた賃料を見せる包み（rental_choices.RentView：IK-117）
    ctx = _rc.RentView(_Indexed(ctx))  # type: ignore[assignment]
    out = ModuleInputs()
    _pension(ctx, out)
    _windfall(ctx, out)
    _other_misc(ctx, out)  # _pension・_windfall の書いた値に未確定の分かれ目を足す
    _retirement(ctx, out)
    _retire_salary(ctx, out)
    _business(ctx, out)
    _blue(ctx, out)
    _stock(ctx, out)
    return out


def _slots(fn: Any) -> Any:
    """slots の関数を索引つきの ctx で呼ぶ。"""
    return lambda ctx: fn(_Indexed(ctx))


def _ct_slots(ctx: YearContext) -> list[DecisionSlot]:
    return ct_slots(ctx, _person_bids(ctx))


DECISIONS: tuple[DecisionSpec, ...] = (
    DecisionSpec(kind=K_JIGYO, slots=_slots(_jigyo_slots)),
    DecisionSpec(kind=K_HOME, slots=_slots(_home_slots)),
    DecisionSpec(kind=K_RELATED, slots=_slots(_related_slots)),
    DecisionSpec(kind=K_SHARE, slots=_slots(_share_slots)),
    DecisionSpec(kind=K_BOOK, slots=_slots(_book_slots)),
    DecisionSpec(kind=K_PLAN, slots=_slots(_plan_slots)),
    DecisionSpec(kind=K_RETIRE, slots=_slots(_retire_slots)),
    DecisionSpec(kind=K_STOCK, slots=_slots(_stock_slots)),
    DecisionSpec(kind=K_LARGE_HOLDER, slots=_slots(_large_slots)),
    DecisionSpec(kind=K_RENT_SCALE, slots=_slots(_rent_scale_slots)),
    DecisionSpec(kind=K_PARTNER, slots=_slots(_partner_slots)),
    DecisionSpec(kind=K_PENSION_NATURE, slots=_slots(_pension_nature_slots)),
    DecisionSpec(kind=K_SEIKEI, slots=_slots(_family_slots)),
    DecisionSpec(kind=K_REASONABLE, slots=_slots(_reasonable_slots)),
    DecisionSpec(kind=K_DEP_CHOICE, slots=_slots(dep_slots)),
    DecisionSpec(kind=K_DEP_CLASS, slots=lambda ctx: ()),
    DecisionSpec(kind=K_EMPLOY, slots=lambda ctx: ()),  # 入力があるときだけ読む（未入力は売上に数えて未確定：_business）
    DecisionSpec(kind=inv.J_INVENTORY, slots=lambda ctx: ()),  # 入力があるときだけ読む（未入力で棚卸しの記録もなければ c-入力：IK-108）
    DecisionSpec(kind=K_CT, slots=_slots(_ct_slots)),
    # 入力があるときだけ読む（2026-11-12。未入力は原則で計算する：prior_years.py・rental_choices.py の docstring）
    DecisionSpec(kind=_prior.K_CASH, slots=lambda ctx: ()),  # IK-64・IK-115
    DecisionSpec(kind=_rc.K_RENT_MATERIAL, slots=lambda ctx: ()),  # IK-116・IK-118（駐車場の未入力は未確定）
    DecisionSpec(kind=_rc.K_RENT_TIMING, slots=lambda ctx: ()),  # IK-117・IK-119
)

RECORD_KINDS: frozenset[str] = frozenset(
    {
        "pension_payment",
        "windfall_receipt",
        "retirement_payment",
        "retirement_record",
        "business",
        "business_receipt",
        "business_expense",
        "payroll_paid",
        "blue_return_procedure",
        "bookkeeping_status",
        "ct_liability",
        "invoice_registration",
        "ct_return",
        "dividend",
        "security_sale",
        "brokerage_annual",
        "benefit_receipt",
        "rent_flow",
        "lease",
        "rental_property",
        "rental_inventory",
        "loan",
        "depreciable_asset",
        "casualty",  # 業務用の資産の災害等の損失（所法51。雑損控除は other_deductions も同じ種類を使う）
        "business_engagement",
        "family_employee_notice",
        "inventory_count",  # 棚卸資産の売上原価（IK-108）
        "inventory_method_notice",
        "household_consumption",  # 家事消費等（IK-109）
        "bad_debt",  # 貸倒れ（IK-110）
        "special_depreciation",  # 割増償却・特別償却の額（外部の値。IK-112：special_dep.py）
        "prior_income_fixed",  # 前々年分の業務の収入金額（所法120⑥・所令196の2。IK-114：prior_years.py）
    }
)

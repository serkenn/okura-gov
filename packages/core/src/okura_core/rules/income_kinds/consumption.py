"""消費税等の経理方式の所得への反映（D20・D22 S17）。

消費税そのものは計算しない（D20）。課税事業者（ct_liability の not_exempt・invoice_registration）の業務について：
- 経理方式は選択（`選択.消費税等の経理方式`）で、未入力なら税込（原則）・税込（未払金に計上）・税抜の全部で評価する（D21 R6・D22 S17）。
- 税込（免税事業者を含む）：売上・経費は記録の額のまま。納付すべき消費税等は、納税申告書の提出の日（更正・決定の日）の年分の必要経費（経理通達7）。
  ただし未払金に計上した年の必要経費とすることができる（同ただし書）。還付は総収入金額（経理通達8）で、負の必要経費として同じ計算に入れる。
- 税抜：資産を含まない取引なら「税込の売上 − 税込の経費 − その年を課税期間とする納付すべき消費税等」と同じ（実測 invoice §6、仮説 H4）。
  資産については税抜の取得価額を使い、その資産の仮払消費税等（その年に取得した分）を更に差し引く（税抜では資産の分の消費税が償却費に入らず、清算の差額に残るため）。
- 年の途中で免税と課税が変わる年分の税抜経理（資産の取得価額を税抜にするか）、修正申告・更正のある課税期間の税抜経理（清算の年）は一次情報がなく、
  候補の全部で計算して値が分かれれば未確定（D21 R6・D22 S1。仮説 H8）。
消費税等の額は `ct_return`（外部で計算した値。確定申告の種類 final 以外は修正・更正等）から受け取る。附帯税は必要経費にしない。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ...candidates import Candidate
from ...registry import DecisionSlot, YearContext, overlaps_year
from ...result import Means, Split, State
from .common import date_of, undetermined

K_CT = "選択.消費税等の経理方式"

INCLUSIVE = "tax_inclusive"
EXCLUSIVE = "tax_exclusive"

CT_CANDIDATES = (
    Candidate({"sales": INCLUSIVE, "accrue_unpaid_tax": False}, "税込経理（納付は申告の年）"),
    Candidate({"sales": INCLUSIVE, "accrue_unpaid_tax": True}, "税込経理（未払金に計上）"),
    Candidate({"sales": EXCLUSIVE}, "税抜経理"),
)
PRIOR_CANDIDATES = (
    Candidate({"sales": INCLUSIVE, "accrue_unpaid_tax": False}, "前年分は申告の年に計上（税込経理の原則）"),
    Candidate({"sales": INCLUSIVE, "accrue_unpaid_tax": True}, "前年分は未払金に計上済み（税込経理）又は税抜経理"),
)


def _returns(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    return sorted((r for r in ctx.records("ct_return") if r["roles"]["person"] == pid), key=lambda r: r["id"])


def _liability(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("ct_liability") if r["roles"]["person"] == pid and overlaps_year(r.get("when"), ctx.year)]


def _registrations(ctx: YearContext, pid: str) -> list[Mapping[str, Any]]:
    return [r for r in ctx.records("invoice_registration") if r["roles"]["person"] == pid and overlaps_year(r.get("when"), ctx.year)]


def _covers_year(records: list[Mapping[str, Any]], year: int) -> bool:
    start, end = _dt.date(year, 1, 1), _dt.date(year, 12, 31)
    spans = sorted((date_of(r["when"]["from_on"]), date_of(r["when"]["to_on"]) if r["when"].get("to_on") else end) for r in records)
    cursor = start
    for a, b in spans:
        if a > cursor:
            return False
        cursor = max(cursor, b + _dt.timedelta(days=1))
    return cursor > end


def status(ctx: YearContext, pid: str) -> str:
    """その年分の消費税の納税義務の状態：'none'（課税事業者の記録がない＝免税として税込）・'taxable'・'mixed'（年の途中で変わる）。

    ct_liability の not_exempt と invoice_registration を課税の期間、ct_liability の exempt を免税の期間とする（判定は外部：D20）。
    記録のない期間は課税事業者の記録がないものとして扱う（基準期間の判定はしない）。
    """
    lias = _liability(ctx, pid)
    regs = _registrations(ctx, pid)
    taxable = [r for r in lias if r["attributes"]["status"] == "not_exempt"] + regs
    if not taxable:
        return "none"
    if _covers_year(taxable, ctx.year) and not [r for r in lias if r["attributes"]["status"] == "exempt"]:
        return "taxable"
    return "mixed"


def ct_slots(ctx: YearContext, businesses_of: Mapping[str, list[str]]) -> list[DecisionSlot]:
    """課税事業者の人の業務ごとに経理方式の選択の1か所。その年分の納付の計上に前年分の選択が要るときは前年分の1か所も足す。"""
    out: list[DecisionSlot] = []
    for pid, bids in sorted(businesses_of.items()):
        if status(ctx, pid) == "none":
            continue
        prior_final = [
            r
            for r in _returns(ctx, pid)
            if r["attributes"]["return_type"] == "final"
            and date_of(r["when"]["to_on"]).year == ctx.year - 1
            and date_of(r["attributes"]["filed_or_decided_on"]).year == ctx.year
        ]
        for bid in bids:
            out.append(
                DecisionSlot(
                    key=f"{pid}:{bid}",
                    target={"person": pid, "business_id": bid, "tax_year": ctx.year},
                    matches=lambda rec, pid=pid, bid=bid: rec["subject"]["person"] == pid and rec["subject"]["business_id"] == bid,
                    candidates=CT_CANDIDATES,
                )
            )
            if prior_final:
                y = ctx.year - 1
                out.append(
                    DecisionSlot(
                        key=f"{pid}:{bid}:前年",
                        target={"person": pid, "business_id": bid, "tax_year": y},
                        matches=lambda rec, pid=pid, bid=bid, y=y: rec["subject"]["person"] == pid
                        and rec["subject"]["business_id"] == bid
                        and rec["when"]["tax_year"] == y,
                        candidates=PRIOR_CANDIDATES,
                        year_filter=False,
                    )
                )
    return out


@dataclass
class CtPlan:
    """1人の年分の経理方式（業務ごとの値から、資産の税抜判定と消費税等の必要経費を作る）。"""

    status: str
    methods: dict[str, str] = field(default_factory=dict)  # 業務の ID → 売上の方式
    fixed_exclusive: dict[str, bool] = field(default_factory=dict)  # 業務の ID → 固定資産を税抜で経理するか
    accrue: dict[str, bool] = field(default_factory=dict)  # 業務の ID → 未払金に計上するか（税込）
    prior_accrued: dict[str, bool] = field(default_factory=dict)  # 業務の ID → 前年分の税額が前年分に計上済みか
    ids: set[str] = field(default_factory=set)
    states: set[State] = field(default_factory=set)
    problems: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)  # 一次情報・語彙がなく値が分かれる1か所（業務の全部の側を未確定にする）


def plan(ctx: YearContext, pid: str, bids: list[str]) -> CtPlan:
    """その人の業務ごとの経理方式を読む（課税事業者の記録がない人は税込）。"""
    st = status(ctx, pid)
    p = CtPlan(st)
    for bid in bids:
        if st == "none":
            p.methods[bid] = INCLUSIVE
            p.fixed_exclusive[bid] = False
            p.accrue[bid] = False
            p.prior_accrued[bid] = False
            continue
        d = ctx.decision(K_CT, f"{pid}:{bid}")
        v = d.value
        p.ids |= set(d.record_ids)
        p.states |= set(d.states)
        sales = v.get("sales") if isinstance(v, Mapping) else None
        p.methods[bid] = sales if sales in (INCLUSIVE, EXCLUSIVE) else INCLUSIVE
        fa = v.get("fixed_assets") if isinstance(v, Mapping) else None
        p.fixed_exclusive[bid] = sales == EXCLUSIVE and (fa is None or fa == EXCLUSIVE)
        if sales == EXCLUSIVE and st == "mixed":
            # 年の途中で免税と課税が変わる年分の税抜経理：資産を含まない取引の所得は税込（未払金に計上）と同じ（実測 invoice §6・仮説 H4）。
            # 資産の取得価額を税抜にするか（免税の期間の取得を含む）は一次情報がない（invoice 仮説 H2・H8-1）。資産があれば両方で値が分かれる
            has_assets = any(
                a["roles"]["owner"] == pid and a["attributes"].get("business_id") == bid and date_of(a["attributes"].get("placed_in_service_on") or a["when"]["from_on"]).year <= ctx.year
                for a in ctx.records("depreciable_asset")
            )
            if has_assets and p.fixed_exclusive[bid]:
                p.splits.append(undetermined(
                    f"一次情報:免税と課税が変わる年分の税抜経理:{pid}:{bid}:{ctx.year}", Means.PRIMARY_SOURCE,
                    {"person": pid, "business_id": bid, "事項": "年の途中で免税事業者と課税事業者が変わる年分の税抜経理で、資産の取得価額を税抜にするか（invoice 仮説 H2・H8-1）"},
                    ("税抜の取得価額", "税込の取得価額"),
                ))
            p.fixed_exclusive[bid] = False
        p.accrue[bid] = bool(v.get("accrue_unpaid_tax")) if isinstance(v, Mapping) else False
        key = f"{pid}:{bid}:前年"
        p.prior_accrued[bid] = False
        if _has(ctx, key):
            dp = ctx.decision(K_CT, key)
            p.ids |= set(dp.record_ids)
            p.states |= set(dp.states)
            value = dp.value
            p.prior_accrued[bid] = bool(isinstance(value, Mapping) and (value.get("sales") == EXCLUSIVE or value.get("accrue_unpaid_tax")))
    return p


def _has(ctx: YearContext, key: str) -> bool:
    try:
        ctx.decision(K_CT, key)
    except KeyError:
        return False
    return True


def tax_amount(r: Mapping[str, Any]) -> int:
    a = r["amounts"]
    return a["consumption_tax"] + a.get("local_consumption_tax", 0)


def tax_expense(
    ctx: YearContext, pid: str, p: CtPlan, bids: list[str], amount: Any = tax_amount
) -> tuple[int, tuple[str, ...], list[tuple[str, tuple[str, ...]]]]:
    """その年分の必要経費（還付は負）に入れる消費税等の額（税抜のときの資産の仮払消費税等は呼び出し側が足す）。"""
    returns = _returns(ctx, pid)
    y = ctx.year
    bids = [b for b in bids if b in p.methods]
    problems: list[tuple[str, tuple[str, ...]]] = []
    if not bids:
        return 0, (), problems
    methods = {p.methods[b] for b in bids}
    accrue = {p.accrue[b] for b in bids}
    prior_accrued = {p.prior_accrued[b] for b in bids}
    ids = tuple(r["id"] for r in returns)
    if len(methods) > 1 or len(accrue) > 1 or len(prior_accrued) > 1:
        # 消費税等の額（課税期間の申告書は人ごと）を業務ごとに分ける語彙がない：分け方で額が変わるので未確定にする
        p.splits.append(undetermined(
            f"事実:業務ごとの消費税等の額:{pid}:{y}", Means.FACT,
            {"person": pid, "ct_return_ids": list(ids), "入力": "経理方式・未払金の計上が違う業務ごとの消費税等の額（ct_return.attributes.business_breakdown を書けば決まる）"},
        ))
        return 0, ids, problems
    method = methods.pop()
    acc = accrue.pop()
    prior = prior_accrued.pop()
    filed = [r for r in returns if date_of(r["attributes"]["filed_or_decided_on"]).year == y]
    this_final = [r for r in returns if r["attributes"]["return_type"] == "final" and date_of(r["when"]["to_on"]).year == y]
    prior_final = [r for r in filed if r["attributes"]["return_type"] == "final" and date_of(r["when"]["to_on"]).year == y - 1]
    total = 0
    if method == EXCLUSIVE:
        # 修正申告・更正・決定の額をどの年分で清算するかの一次情報がない（invoice 仮説 H8-3）：課税期間の年分（税抜の清算）か、
        # 提出・決定の年分（税込の原則と同じ）かの両方で計算し、違えば未確定
        period_side = sum(amount(r) for r in returns if r["attributes"]["return_type"] != "final" and date_of(r["when"]["to_on"]).year == y)
        filed_side = sum(amount(r) for r in filed if r["attributes"]["return_type"] != "final")
        if period_side != filed_side:
            p.splits.append(undetermined(
                f"一次情報:税抜経理の修正申告等の清算の年:{pid}:{y}", Means.PRIMARY_SOURCE,
                {"person": pid, "ct_return_ids": [r["id"] for r in returns if r["attributes"]["return_type"] != "final"],
                 "事項": "税抜経理で修正申告・更正・決定がある課税期間の消費税等をどの年分で清算するか（invoice 仮説 H8-3）"},
                ("課税期間の年分", "提出・決定の年分"),
            ))
        total += period_side
        if not this_final:
            problems.append(("税抜経理：その年を課税期間とする消費税等の申告書（ct_return の final）がない（納付すべき消費税等の額が決まらない）", ids or (pid,)))
            return 0, ids, problems
        total += sum(amount(r) for r in this_final)
        if not prior:
            total += sum(amount(r) for r in prior_final)  # 前年分は税込の原則：その年に提出した前年分の税額は、提出の年の必要経費に入る
    else:
        if acc:
            if not this_final:
                problems.append(("税込経理で未払金に計上するが、その年を課税期間とする消費税等の申告書の記載（ct_return）がない", ids or (pid,)))
                return 0, ids, problems
            total += sum(amount(r) for r in this_final)
        total += sum(
            amount(r)
            for r in filed
            if not (r["attributes"]["return_type"] == "final" and date_of(r["when"]["to_on"]).year == y and acc)
            and not (prior and r in prior_final)
        )
    return total, ids, problems



BREAKDOWN_REASON = (
    "入力の矛盾：消費税等の申告書（ct_return）の業務ごとの内訳（attributes.business_breakdown）の合計が申告書の額と合わない、又は同じ業務が2回ある"
)


def _breakdown_amount(r: Mapping[str, Any], bid: str) -> int:
    for x in r["attributes"]["business_breakdown"]:
        if x["business_id"] == bid:
            return x["consumption_tax"] + x.get("local_consumption_tax", 0)
    return 0


def tax_expense_by_business(
    ctx: YearContext, pid: str, p: CtPlan, bids: list[str]
) -> tuple[dict[str, int], tuple[str, ...], list[tuple[str, tuple[str, ...]]]] | None:
    """業務ごとの消費税等の必要経費（ct_return の business_breakdown。2026-11-12 の語彙：IK-52・56）。

    その人の申告書が1つもないか、内訳のない申告書が1つでもあれば None（呼び出し側は人ごとの額で計算し、分け方が要れば未確定にする）。
    内訳があれば業務ごとに tax_expense を当てる（経理方式・未払金の計上が業務ごとに違ってもよい）。
    """
    returns = _returns(ctx, pid)
    bids = [b for b in bids if b in p.methods]
    if not returns or not bids or any(r["attributes"].get("business_breakdown") is None for r in returns):
        return None
    ids = tuple(r["id"] for r in returns)
    problems: list[tuple[str, tuple[str, ...]]] = []
    for r in returns:
        rows = r["attributes"]["business_breakdown"]
        if (
            sum(x["consumption_tax"] for x in rows) != r["amounts"]["consumption_tax"]
            or sum(x.get("local_consumption_tax", 0) for x in rows) != r["amounts"].get("local_consumption_tax", 0)
            or len({x["business_id"] for x in rows}) != len(rows)
        ):
            problems.append((BREAKDOWN_REASON, (r["id"],)))
    if problems:
        return {}, ids, problems
    out: dict[str, int] = {}
    for b in bids:
        total, _, pr = tax_expense(ctx, pid, p, [b], amount=lambda r, b=b: _breakdown_amount(r, b))
        out[b] = total
        problems += pr
    return out, ids, problems

__all__ = ["CT_CANDIDATES", "CtPlan", "EXCLUSIVE", "INCLUSIVE", "K_CT", "ct_slots", "plan", "status", "tax_expense", "tax_expense_by_business"]

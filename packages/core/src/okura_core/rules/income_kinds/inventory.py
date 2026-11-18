"""規則モジュール income_kinds：棚卸資産の売上原価（所法47・所法37①）、家事消費等（所法39・40①一）、貸倒れ（所法51②・所令141・所法64①・所法51④）。

docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md（以下 PS）、仮説 docs/hypotheses/20261112_impl-research6_tanaoroshi-model.md（以下 H）、
推測 docs/inferences/20261112_impl-research6_tanaoroshi-cases.md。README の IK-108〜IK-111。

- 売上原価＝期首棚卸高＋仕入高－期末棚卸高（所法37①・47①。H1）。仕入（business_expense の merchandise・materials）は支出の年の必要経費に数えたまま、
  期首－期末の差（inventory_change）を必要経費に足す。
- 事業所得の期末棚卸高（所法47①・所令99〜102。H2）：評価の方法は届出（所令100②：事業を開始した年分の確定申告期限まで）・変更の承認（所令101：
  採用しようとする年の3月15日までの申請、12月31日までに処分がなければ承認とみなす）・特別な方法の承認（所令99の2：承認の日の年分から）で決め、
  届出がなければ最終仕入原価法による原価法（所令102①）。低価法は青色申告の承認を受けた年分だけ（所令99① かっこ書）。承認がない年分は、届出の低価法の
  基礎の原価法で評価した額を読む（法令の読み：H2-3）。その方法で評価した棚卸しの記録（inventory_count）がなければ c-入力（評価できない）。
- 業務に係る雑所得の売上原価（所法37①。H3）：所法47 は事業所得だけ。所基通47−12 の「令第99条第1項第1号に掲げる評価の方法に準じて」の読みで、原価法の
  いずれかで評価した記録を使う（法令の読み）。2つ以上の方法の記録があり額が違えば c-入力。
- 期首棚卸高：その年の期首の棚卸し（count_type opening。年の初日・業務の開始の日）、なければ前年の期末の棚卸し（前年の評価の方法）、業務をその年に始めたなら0。
- 棚卸しの記録も 判断.棚卸資産の有無（偽）もなく、仕入・家事消費・前年の棚卸しのある業務は、期末棚卸高が分からないので c-入力（仕入の全額を経費にしない）。
- 家事消費等（所法39・40①一）：所基通39−1（通常他に販売する価額）・39−2（事業を営む者が取得価額以上で帳簿に記載して総収入金額に算入し、通常の価額の
  おおむね70%以上なら、その額）。業務に係る雑所得は 39−2 の「事業を営む者」に当たらないので 39−1 の価額。
- 貸倒れ：事業（事業所得・事業的規模の不動産所得）は所法51②・所令141 で損失の日の年分の必要経費。業務（雑所得・事業的規模でない不動産所得）は、
  収入金額の債権（売上・賃料）・返品値引き・無効の行為は所法64①（収入金額を算入した年分の所得の金額の計算上なかったものとみなす。所令180②二の額
  〔その所得の金額から、なかったものとした場合の金額を控除した残額。赤字なら0〕を上限）、それ以外の債権（貸付金・前渡金・保証金・その他）は所法51④
  （その所得の金額を限度に損失の日の年分の必要経費）。所令180②一（総所得金額・退職所得金額の合計）が二号より低くなりうる人（他の所得の側に損失・
  純損失・雑損失の繰越がある人）は対象外（c-限界：H4-3）。
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

PS = "docs/public-sources/20261112_impl-research6_tanaoroshi-laws-and-nta.md"

#: 仕入（売上原価の基礎）の費目。
PURCHASE_CATEGORIES = frozenset({"merchandise", "materials"})
#: 法定の評価の方法（所令102①：最終仕入原価法による原価法）。
STATUTORY = ("final_purchase_cost", False)
#: 業務の 所法64① の対象（収入金額の債権の回収不能・返品値引き・無効の行為）。
REVENUE_RECEIVABLES = frozenset({"sales", "rent"})
REVENUE_EVENTS = frozenset({"returns_or_discounts", "invalid_act"})

J_INVENTORY = "判断.棚卸資産の有無"

UNKNOWN_CLOSING_REASON = (
    "入力の不足：期末の棚卸高が分からない（仕入・家事消費・前年の棚卸しがあるのに、その年の12月31日〔年の中途の死亡はその日〕の棚卸しの記録 inventory_count も、"
    "判断.棚卸資産の有無（偽：棚卸資産を有しない）もない）。仕入の全額をその年の必要経費にする読みでは計算しない（所法47①・37①）"
)
UNKNOWN_OPENING_REASON = (
    "入力の不足：期首の棚卸高が分からない（前年の12月31日の棚卸しの記録・その年の期首の棚卸しの記録・前年の 判断.棚卸資産の有無 のどれもない）"
)
METHOD_MISSING_REASON = (
    "入力の不足：評価の方法（届出・承認・法定の最終仕入原価法：所法47①・所令99〜102）で評価した期末の棚卸しの記録がない。その方法の評価額を inventory_count に書けば決まる"
)
CLASS_MISMATCH_REASON = "入力の不足：評価の方法の届出が棚卸資産の区分（asset_class）ごとなのに、棚卸しの記録に区分がない（所令100①）"
MISC_METHODS_REASON = "入力の矛盾：業務に係る雑所得の棚卸しの記録に、同じ日・区分で評価の方法の違う額が2つ以上ある（どれを売上原価の基礎にするか決まらない）"
HOUSEHOLD_PRICE_REASON = (
    "入力の不足：家事消費・贈与（household_consumption）に通常他に販売する価額（normal_sales_price）がない（所基通39−1。帳簿に記載した額を使う39−2 の判定にも要る）"
)
BAD_DEBT_YEAR_REASON = (
    "入力の不足：業務（事業でない）の収入金額の債権の貸倒れ（所法64①）に、その収入金額を総収入金額に算入した年分（revenue_tax_year）がない"
)
BAD_DEBT_CAP_REASON = (
    "所法64① のなかったものとみなす額の上限（所令180②一：直前に確定している総所得金額・退職所得金額の合計）が、ほかの所得の側の損失・前年以前の純損失・雑損失の"
    "繰越控除で二号の額より低くなりうる。一号の額を所得の種類の段で計算する窓口がない（c-限界：仮説 H4-3）"
)


@dataclass
class Valued:
    """評価の結果。value が None なら決まらない（reason）。"""

    value: int | None
    record_ids: tuple[str, ...] = ()
    reason: str | None = None
    reading: bool = False  # 法令の読み（低価法の承認のない年分・業務の評価の方法）


def _d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def _next_business_day(d: _dt.date) -> _dt.date:
    while d.weekday() >= 5:
        d += _dt.timedelta(days=1)
    return d


def method_in_force(
    notices: Sequence[Mapping[str, Any]], start: _dt.date, year: int, asset_class: str | None
) -> tuple[tuple[str, bool], tuple[str, ...]]:
    """その年分の評価の方法（(方法, 低価法か), 根拠の記録）。所令100②・101・99の2・102①。

    notices はその人・業務の inventory_method_notice。asset_class の届出（区分ごと）があればそれを、なければ区分のない届出を見る。
    """
    rel = [n for n in notices if n["attributes"].get("asset_class") in (asset_class, None)]
    # 区分の届出があれば区分のない届出より優先（所令100① の区分ごとの選定）
    specific = [n for n in rel if n["attributes"].get("asset_class") is not None]
    if specific and asset_class is not None:
        rel = specific + [n for n in rel if n["attributes"].get("asset_class") is None and n["attributes"]["procedure"] != "selection_notice"]
    events: list[tuple[int, _dt.date, tuple[str, bool], str]] = []  # (適用の初年, 日, 方法, 記録)
    deadline = _next_business_day(_dt.date(start.year + 1, 3, 15))  # 開始の日の属する年分の確定申告期限（所法120①。土日は翌日）
    selections = sorted((n for n in rel if n["attributes"]["procedure"] == "selection_notice"), key=lambda n: (n["when"]["on"], n["id"]))
    timely = [n for n in selections if _d(n["when"]["on"]) <= deadline]
    if timely:
        n = timely[0]
        events.append((start.year, _d(n["when"]["on"]), (n["attributes"]["method"], bool(n["attributes"].get("lower_of_cost"))), n["id"]))
    for n in sorted(rel, key=lambda n: (n["when"]["on"], n["id"])):
        a, on = n["attributes"], _d(n["when"]["on"])
        m = (a["method"], bool(a.get("lower_of_cost")))
        if a["procedure"] == "special_method_approved":
            events.append((on.year, on, m, n["id"]))  # 所令99の2①：承認を受けた日の属する年分以後
        elif a["procedure"] == "change_application":
            first = on.year if on <= _dt.date(on.year, 3, 15) else on.year + 1  # 所令101②：採用しようとする年の3月15日まで
            end = _dt.date(first, 12, 31)
            rejected = [
                x for x in rel
                if x["attributes"]["procedure"] == "change_rejected" and on <= _d(x["when"]["on"]) <= end and x["attributes"]["method"] == a["method"]
            ]  # fmt: skip
            if not rejected:  # 承認の通知か、12月31日までに処分がなければ承認とみなす（所令101⑤）
                events.append((first, on, m, n["id"]))
    applicable = [e for e in events if e[0] <= year]
    if not applicable:
        return STATUTORY, ()
    applicable.sort(key=lambda e: (e[0], e[1]))
    _, _, method, rid = applicable[-1]
    return method, (rid,)


def _counts_on(counts: Iterable[Mapping[str, Any]], on: _dt.date, opening: bool) -> list[Mapping[str, Any]]:
    out = []
    for r in counts:
        if _d(r["when"]["on"]) != on:
            continue
        is_open = r["attributes"].get("count_type") == "opening"
        if is_open == opening:
            out.append(r)
    return out


def value_counts(
    counts: Sequence[Mapping[str, Any]],
    *,
    business: bool,
    notices: Sequence[Mapping[str, Any]],
    start: _dt.date,
    year: int,
    blue: bool,
) -> Valued:
    """1つの日の棚卸しの記録（区分ごと・方法ごと）から評価額を決める。business は事業所得（所法47）か。"""
    if not counts:
        return Valued(None)
    classes = sorted({r["attributes"].get("asset_class") or "" for r in counts})
    has_class_notice = any(n["attributes"].get("asset_class") for n in notices)
    if business and has_class_notice and classes == [""]:
        return Valued(None, tuple(r["id"] for r in counts), CLASS_MISMATCH_REASON)
    total = 0
    ids: list[str] = []
    reading = False
    for cls in classes:
        rows = [r for r in counts if (r["attributes"].get("asset_class") or "") == cls]
        if business:
            (method, lower), basis_ids = method_in_force(notices, start, year, cls or None)
            if lower and not blue:
                lower = False  # 所令99① かっこ書：青色申告の承認がない年分は原価法だけ（届出の低価法の基礎の原価法：法令の読み H2-3）
                reading = True
            hit = [r for r in rows if r["attributes"]["valuation_method"] == method and bool(r["attributes"].get("lower_of_cost")) == lower]
            if not hit:
                return Valued(None, tuple(r["id"] for r in rows) + basis_ids, METHOD_MISSING_REASON)
            total += sum(r["amounts"]["valuation"] for r in hit)  # 同じ区分・方法の記録が2つ以上なら合計（事業所別などの内訳：所基通47−13）
            ids += [r["id"] for r in hit] + list(basis_ids)
        else:
            cost = [r for r in rows if not r["attributes"].get("lower_of_cost")]
            methods = {r["attributes"]["valuation_method"] for r in cost}
            if not cost:
                return Valued(None, tuple(r["id"] for r in rows), MISC_METHODS_REASON)
            if len(methods) > 1:
                sums = {m: sum(r["amounts"]["valuation"] for r in cost if r["attributes"]["valuation_method"] == m) for m in methods}
                if len(set(sums.values())) > 1:
                    return Valued(None, tuple(r["id"] for r in rows), MISC_METHODS_REASON)
                m0 = sorted(methods)[0]
                cost = [r for r in cost if r["attributes"]["valuation_method"] == m0]
            total += sum(r["amounts"]["valuation"] for r in cost)
            ids += [r["id"] for r in cost]
            reading = True  # 業務の評価の方法：所基通47−12 の準用の読み（H3）
    return Valued(total, tuple(ids), None, reading)


@dataclass
class InventoryResult:
    """1つの業務の売上原価の材料。"""

    opening: int = 0
    closing: int = 0
    record_ids: list[str] = field(default_factory=list)
    problem: str | None = None
    problem_ids: tuple[str, ...] = ()
    reading: bool = False
    relevant: bool = False


def inventory_for(
    *,
    counts: Sequence[Mapping[str, Any]],
    notices: Sequence[Mapping[str, Any]],
    judgments: Mapping[int, tuple[bool, str]],
    business: bool,
    start: _dt.date,
    year: int,
    year_end: _dt.date,
    blue: Mapping[int, bool],
    has_activity: bool,
) -> InventoryResult:
    """業務の期首・期末の棚卸高（純粋関数）。judgments は年分 → (棚卸資産を有するか, 判断の ID)。blue は年分 → 青色申告の承認。

    has_activity：その年の仕入・家事消費がある。関係のない業務（仕入も棚卸しも判断もない）は relevant=False で 0・0。
    """
    res = InventoryResult()
    prior_end = _dt.date(year - 1, 12, 31)
    closing_counts = _counts_on(counts, year_end, opening=False)
    opening_counts = [r for r in counts if r["attributes"].get("count_type") == "opening" and _d(r["when"]["on"]).year == year]
    prior_counts = _counts_on(counts, prior_end, opening=False)
    j_now, j_prior = judgments.get(year), judgments.get(year - 1)
    res.relevant = bool(has_activity or closing_counts or opening_counts or prior_counts or j_now is not None)
    if not res.relevant:
        return res
    # 期末
    if j_now is not None and j_now[0] is False:
        res.closing = 0
        res.record_ids.append(j_now[1])
        if closing_counts:
            res.record_ids += [r["id"] for r in closing_counts]  # 判断（有しない）と記録の両方：記録を使う
            v = value_counts(closing_counts, business=business, notices=notices, start=start, year=year, blue=blue.get(year, False))
            if v.value is None:
                res.problem, res.problem_ids = v.reason, v.record_ids
                return res
            res.closing, res.reading = v.value, res.reading or v.reading
    else:
        v = value_counts(closing_counts, business=business, notices=notices, start=start, year=year, blue=blue.get(year, False))
        if v.value is None:
            res.problem = v.reason or UNKNOWN_CLOSING_REASON
            res.problem_ids = v.record_ids + ((j_now[1],) if j_now else ())
            return res
        res.closing, res.reading = v.value, v.reading
        res.record_ids += list(v.record_ids) + ([j_now[1]] if j_now else [])
    # 期首
    if opening_counts:
        v = value_counts(opening_counts, business=business, notices=notices, start=start, year=year, blue=blue.get(year, False))
        if v.value is None:
            res.problem, res.problem_ids = v.reason, v.record_ids
            return res
        res.opening, res.reading = v.value, res.reading or v.reading
        res.record_ids += list(v.record_ids)
    elif start.year >= year:
        res.opening = 0  # その年に業務を始めた（期首の棚卸しの記録がなければ0）
    elif prior_counts:
        v = value_counts(prior_counts, business=business, notices=notices, start=start, year=year - 1, blue=blue.get(year - 1, False))
        if v.value is None:
            res.problem, res.problem_ids = v.reason, v.record_ids
            return res
        res.opening, res.reading = v.value, res.reading or v.reading
        res.record_ids += list(v.record_ids)
    elif j_prior is not None and j_prior[0] is False:
        res.opening = 0
        res.record_ids.append(j_prior[1])
    else:
        res.problem, res.problem_ids = UNKNOWN_OPENING_REASON, tuple(res.record_ids)
    return res


def household_amount(rec: Mapping[str, Any], *, business: bool) -> tuple[int | None, bool]:
    """家事消費・贈与1件の総収入金額に算入する額（所基通39−1・39−2）と、39−2 の帳簿の額を使ったか。None は c-入力。"""
    a = rec["amounts"]
    price, booked, cost = a.get("normal_sales_price"), a.get("recorded_amount"), a.get("acquisition_cost")
    if price is None:
        return None, False
    if business and booked is not None and cost is not None and booked >= cost and booked * 10 >= price * 7:
        return int(booked), True  # 39−2：取得価額以上・通常の価額のおおむね70%以上（ちょうど70%は認める読み：H5）
    return int(price), False


def bad_debt_route(rec: Mapping[str, Any], *, business_scale: bool) -> str:
    """貸倒れ1件の当て方：'51-2'（事業）・'64-1'（業務の収入金額の債権など）・'51-4'（業務のそれ以外の債権）。"""
    if business_scale:
        return "51-2"
    a = rec["attributes"]
    if a.get("event") in REVENUE_EVENTS or a.get("receivable_type") in REVENUE_RECEIVABLES or a.get("receivable_type") is None:
        return "64-1"
    return "51-4"


def deemed_uncollectible(amount: int, side_income: int) -> int:
    """所法64①・所令180②二：なかったものとみなす額（その所得の金額から、なかったものとした場合の金額を控除した残額が上限。赤字なら0）。"""
    return max(0, min(amount, side_income))


__all__ = [
    "BAD_DEBT_CAP_REASON",
    "BAD_DEBT_YEAR_REASON",
    "CLASS_MISMATCH_REASON",
    "HOUSEHOLD_PRICE_REASON",
    "InventoryResult",
    "J_INVENTORY",
    "METHOD_MISSING_REASON",
    "MISC_METHODS_REASON",
    "PURCHASE_CATEGORIES",
    "UNKNOWN_CLOSING_REASON",
    "UNKNOWN_OPENING_REASON",
    "Valued",
    "bad_debt_route",
    "deemed_uncollectible",
    "household_amount",
    "inventory_for",
    "method_in_force",
    "value_counts",
]

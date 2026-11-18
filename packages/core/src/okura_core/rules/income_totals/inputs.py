"""規則モジュール income_totals の situation への写し方：前年以前の申告書の記載（filed_document）→ その年分の入力、
選択.株式等の申告 → 上場株式等の譲渡損失の損益通算・繰越控除を適用するか。

前年以前の記載は、その年分の入力（事実）にする（式でほかの年分の値を引かない：packages/core/README.md §6.1・§10）。
申告書の記載の読み方（README §3。中間表現の語彙 reported_amounts の item の意味はこのモジュールの読み）：

- 申告書：kind filed_document、document_type が final_return・loss_return・quasi_final_return、attributes.tax_year の年分のもの。
  同じ年分に2件以上あれば（修正申告・更正など）どれを使うかを決めない（対象外）。
- 純損失：生じた年分 o の申告書の net_loss_total（o の純損失の金額）から、o の申告書の net_loss_carryback（繰り戻した額）と、
  o+1〜前年の申告書の net_loss_carryforward_used（origin_tax_year＝o。繰越控除で使った額）を引いた残り。o は前年以前3年内
  （所法70①）。o が青色申告書の年分か（所法70①）は、青色申告の承認の通知（blue_return_procedure の approval_notice、
  first_tax_year ≦ o）があり、却下・取消し・取りやめ・廃止の記録がないときだけ青色とする。決まらなければ対象外
  （白色の年の変動所得・被災事業用資産の損失の繰越は後の段：D21 R3）。o〜前年の申告書が全部あること（所法70④）。
- 雑損失・上場株式等の譲渡損失：前年の申告書の casualty_loss_carryforward・listed_stock_loss_carryforward（origin_tax_year の年に
  生じ、翌年以後に繰り越す額）。生じた年分〜前年の申告書が全部あること（所法71②・措法37の12の2⑦）。3年を超える前の年の損失の
  記載は、特定非常災害の5年の繰越（後の段：D22 S12）か矛盾なので対象外。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...candidates import Candidate
from ...money import INT32_MAX
from ...registry import DecisionSlot, DecisionSpec, ModuleInputs, YearContext, overlaps_year
from ...result import OutOfScopeCategory, OutOfScopeReason
from .basis import SECOND_PRIOR_RULE

V_NET = "所得税_繰り越された純損失の金額"
V_CASUALTY = "所得税_繰り越された雑損失の金額"
V_LISTED = "所得税_繰り越された上場株式等の譲渡損失の金額"
V_OFFSET = "所得税_上場株式等の譲渡損失の損益通算を適用するか"
V_CARRY = "所得税_上場株式等の譲渡損失の繰越控除を適用するか"
V_PREV_TAXABLE = "所得税_前年分の課税総所得金額"
V_PREV_TAX = "所得税_前年分の税額控除後の所得税の額"
V_PREV_RET = "所得税_前年分の課税退職所得金額"
V_PREV_TIMBER = "所得税_前年分の課税山林所得金額"
V_PREV_RET_STATED = "所得税_前年分の課税退職所得金額等の記載があるか"
V_PREV_BLUE = "所得税_前年分に青色申告書を提出したか"
V_CHOSEN_BACK = "所得税_繰り戻す純損失の金額の選択"
V_TIMELY = "所得税_その年分の確定申告書を期限内に提出するか"
V2_BACK = "所得税_前々年分に繰り戻す純損失の金額"
V2_TAXABLE = "所得税_前々年分の課税総所得金額"
V2_RET = "所得税_前々年分の課税退職所得金額"
V2_TAX = "所得税_前々年分の税額控除後の所得税の額"
V2_PRIOR = "所得税_前々年分に既に繰り戻した純損失の金額"
V2_VARIABLES = (V2_BACK, V2_TAXABLE, V2_RET, V2_TAX, V2_PRIOR)

#: 繰越の期間「前年以前三年内」（所法70①・71①、措法37の12の2⑤：docs/public-sources/20261109_round2_aoiro-laws-and-nta.md §5.2、
#: docs/public-sources/20261109_round3_shibo-shukkoku-laws-and-nta.md §8、docs/public-sources/20261109_round2b_kabu-law-and-nta.md §6）。
#: 令和7年分・令和8年分の版で同じ（特定非常災害の5年は後の段：D22 S12）。
CARRY_YEARS = 3

RETURN_TYPES = frozenset({"final_return", "loss_return", "quasi_final_return"})
#: 青色申告の承認があったと読まない手続（記録があれば青色かを判定しない：所法145・150・151）。
BLUE_UNDECIDED = frozenset({"rejection_notice", "revocation_notice", "withdrawal_notice", "business_transfer_or_closure"})

STOCK_CHOICE = "選択.株式等の申告"
CARRYBACK_CHOICE = "選択.損失申告と繰戻し"
PLAN_JUDGMENT = "計画.申告の方法と時期"
SUSPENSION_JUDGMENT = "判断.事業の休止・重要部分の譲渡"
#: 選択.損失申告と繰戻し の前々年分へ繰り戻す額の欄（所法140⑤・141④）。
SECOND_FIELD = "second_prior_year_carryback_amount"
#: 所令272① の事実に当たる判断の値（事業の全部の相当期間の休止・重要部分の譲渡）。
SUSPENSION_EVENTS = frozenset({"considerable_suspension", "important_part_transfer"})
SUSPENSION_CANDIDATES = (
    Candidate("considerable_suspension", "事業の全部の相当期間の休止"),
    Candidate("important_part_transfer", "重要部分の譲渡"),
    Candidate("neither", "どちらでもない"),
)
#: 前々年分への繰戻しで使う所法89① の表が docs で確かめられている最初の年分（所法R6・R7・R8 で同文：
#: docs/public-sources/20261109_impl-prep_zeigaku-tax-calc.md §2。令和5年分〔asof 2023-12-31〕・令和6年分も同じ表：
#: docs/public-sources/20261112_impl-research4_shotoku-laws-and-nta.md §2。2026-11-12 に IT-15 を解いた）。
SECOND_RATE_FROM = 2023
#: 繰戻しの選択が未入力のときの候補（D22 S20）。全額は int の上限の値で表し、式で純損失の金額に切り詰める。
CARRYBACK_CANDIDATES = (Candidate(0, "繰り戻さない"), Candidate(INT32_MAX, "全額を繰り戻す"))
#: 計画.申告の方法と時期の候補（income_kinds の青色申告特別控除と同じ1か所：kind と key が同じなら1回だけ評価される）。
PLAN_CANDIDATES = (
    Candidate({"method": "e_tax", "within_deadline": True, "statements_attached": True}, "期限内・e-Tax・書類の添付あり"),
    Candidate({"method": "paper", "within_deadline": True, "statements_attached": True}, "期限内・書面・書類の添付あり"),
    Candidate({"method": "paper", "within_deadline": False, "statements_attached": True}, "期限後"),
)
#: 上場株式等の所得の材料の記録（損益通算・繰越控除の選択の分かれ目を置く人を絞る）。
STOCK_RECORDS = ("dividend", "security_sale", "brokerage_annual")
#: 純損失が生じうる業務の記録（繰戻しの選択の分かれ目を置く人を絞る）。
LOSS_MATERIAL = ("business", "business_receipt", "business_expense", "rental_property", "rent_flow", "lease")
BOOL_CANDIDATES = (Candidate(True, "true"), Candidate(False, "false"))


def offset_key(person: str) -> str:
    return f"{person}:上場株式等の譲渡損失の損益通算"


def carry_key(person: str) -> str:
    return f"{person}:上場株式等の譲渡損失の繰越控除"


@dataclass
class Carried:
    """繰り越された損失の入力1つ。reasons があれば対象外（値は0を入れる）。"""

    value: int = 0
    record_ids: set[str] = field(default_factory=set)
    reasons: list[str] = field(default_factory=list)
    #: 生じた年分 → value の内訳（第四表（二）の「4 繰越損失を差し引く計算」の年分ごとの Ⓐ。2026-11-12：filing.py）
    by_year: dict[int, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 申告書の記載
# ---------------------------------------------------------------------------


def returns_by_year(ctx: YearContext, person: str) -> dict[int | None, list[Mapping[str, Any]]]:
    out: dict[int | None, list[Mapping[str, Any]]] = {}
    for rec in ctx.records("filed_document"):
        a = rec["attributes"]
        if rec["roles"].get("filer") != person or a["document_type"] not in RETURN_TYPES:
            continue
        out.setdefault(a.get("tax_year"), []).append(rec)
    return out


def _items(rec: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    return [it for it in rec["attributes"].get("reported_amounts", []) if it["item"] == name]


def _one(rets: Mapping[int | None, list[Mapping[str, Any]]], year: int, c: Carried) -> Mapping[str, Any] | None:
    recs = rets.get(year, [])
    if len(recs) > 1:
        c.record_ids |= {r["id"] for r in recs}
        c.reasons.append(f"{year}年分の申告書の記録が複数ある（修正申告・更正など）。どの記載を使うかはこの版では決めない")
        return None
    return recs[0] if recs else None


def _require(rets: Mapping[int | None, list[Mapping[str, Any]]], years: range, c: Carried, law: str) -> None:
    for t in years:
        r = _one(rets, t, c)
        if r is None and not rets.get(t):
            c.reasons.append(f"{t}年分の申告書の記録がなく、連続して確定申告書を提出したか（{law}）が記録から分からない")
        elif r is not None:
            c.record_ids.add(r["id"])


def _undated(rets: Mapping[int | None, list[Mapping[str, Any]]], names: tuple[str, ...], c: Carried) -> None:
    for r in rets.get(None, []):
        if any(_items(r, n) for n in names):
            c.record_ids.add(r["id"])
            c.reasons.append("年分（attributes.tax_year）のない申告書に損失の記載がある")


def blue_evidence(ctx: YearContext, person: str, year: int) -> tuple[bool, tuple[str, ...]]:
    """その年分が青色申告書による申告か（所法70①）を、承認の通知の記録で確かめる。確かめられなければ False（呼ぶ側が対象外にする）。

    year より後の年の事業の全部の譲渡・廃止の記録（business_transfer_or_closure）は、year 分の青色に関係しないので見ない
    （所法140⑤ の事実そのもの。2026-11-11）。却下・取消し・取りやめの記録は年分の欄で確かめず、あれば決めない（安全側）。
    """
    recs = [
        r
        for r in ctx.records("blue_return_procedure")
        if r["roles"].get("person") == person
        and not (r["attributes"]["procedure"] == "business_transfer_or_closure" and int(str(r["when"]["on"])[:4]) > year)
    ]
    ids = tuple(sorted(r["id"] for r in recs))
    if any(r["attributes"]["procedure"] in BLUE_UNDECIDED for r in recs):
        return False, ids
    ok = any(
        r["attributes"]["procedure"] == "approval_notice"
        and r["attributes"].get("first_tax_year") is not None
        and r["attributes"]["first_tax_year"] <= year
        for r in recs
    )
    return ok, ids


def carried_net_loss(ctx: YearContext, person: str, rets: Mapping[int | None, list[Mapping[str, Any]]]) -> Carried:
    """所法70①④・所令201①：前年以前3年内の青色の年分の純損失のうち、繰り戻さず、まだ控除していない額の合計。"""
    c = Carried()
    y = ctx.year
    _undated(rets, ("net_loss_total", "net_loss_carryforward_used", "net_loss_carryback"), c)
    for t in range(y - CARRY_YEARS, y):  # 特定非常災害の5年の繰越（所法70の2）を使った記載は後の段
        r = _one(rets, t, c)
        for it in _items(r, "net_loss_carryforward_used") if r is not None else []:
            o = it.get("origin_tax_year")
            if o is not None and o < t - CARRY_YEARS:
                c.record_ids.add(r["id"])  # type: ignore[index]
                c.reasons.append(f"{t}年分に{o}年分の純損失を繰越控除した記載がある（3年を超える：特定非常災害の5年の繰越は後の段：D22 S12）")
    for o in range(y - CARRY_YEARS, y):
        ro = _one(rets, o, c)
        if ro is None:
            continue
        made = _items(ro, "net_loss_total")
        if any(it.get("origin_tax_year", o) != o for it in made):
            c.record_ids.add(ro["id"])
            c.reasons.append(f"{o}年分の申告書に、ほかの年分に生じた純損失の金額（net_loss_total）の記載がある")
            continue
        generated = sum(it["amount"] for it in made)
        if generated == 0:
            continue
        c.record_ids.add(ro["id"])
        if generated < 0:
            c.reasons.append(f"{o}年分の純損失の金額の記載が負")
            continue
        blue, blue_ids = blue_evidence(ctx, person, o)
        c.record_ids |= set(blue_ids)
        if not blue:
            c.reasons.append(
                f"{o}年分の純損失が青色申告書を提出した年分のもの（所法70①）か記録から決まらない（青色申告の承認の通知で first_tax_year が"
                f"{o}以前のものがあり、却下・取消し・取りやめ・廃止の記録がないときだけ青色とする）。白色の年の変動所得・被災事業用資産の"
                "損失の繰越は後の段（D21 R3）"
            )
            continue
        back = sum(it["amount"] for it in _items(ro, "net_loss_carryback") if it.get("origin_tax_year", o) == o)
        used = 0
        _require(rets, range(o + 1, y), c, "所法70④")
        for t in range(o + 1, y):
            rt = _one(rets, t, c)
            for it in _items(rt, "net_loss_carryforward_used") if rt is not None else []:
                if it.get("origin_tax_year") is None:
                    c.reasons.append(f"{t}年分の申告書の繰越控除で使った純損失（net_loss_carryforward_used）に生じた年分がない")
                elif it["origin_tax_year"] == o:
                    used += it["amount"]
        rest = generated - back - used
        if back < 0 or used < 0 or rest < 0:
            c.reasons.append(f"{o}年分の純損失の金額・繰戻し・繰越控除の記載が合わない（残りが負）")
            continue
        c.value += rest
        c.by_year[o] = c.by_year.get(o, 0) + rest
    return c


def _carried_from_last_return(
    ctx: YearContext, rets: Mapping[int | None, list[Mapping[str, Any]]], item: str, law: str, older: str
) -> Carried:
    """前年の申告書の「翌年以後に繰り越す損失」（item）のうち、前年以前3年内に生じたものの合計。"""
    c = Carried()
    y = ctx.year
    _undated(rets, (item,), c)
    last = _one(rets, y - 1, c)
    if last is None:
        for t in range(y - CARRY_YEARS, y - 1):
            for r in rets.get(t, []):
                if any(it.get("origin_tax_year") is None or it["origin_tax_year"] >= y - CARRY_YEARS for it in _items(r, item)):
                    c.record_ids.add(r["id"])
                    c.reasons.append(f"{t}年分に繰り越す損失の記載があるが、{y - 1}年分の申告書の記録がない（{law}）")
        return c
    for it in _items(last, item):
        o, amount = it.get("origin_tax_year"), it["amount"]
        if amount == 0:
            continue
        c.record_ids.add(last["id"])
        if o is None or amount < 0 or o > y - 1:
            c.reasons.append(f"{y - 1}年分の申告書の繰り越す損失（{item}）の記載に、生じた年分がないか、負の額か、後の年分がある")
            continue
        if o < y - CARRY_YEARS:
            c.reasons.append(f"{y - 1}年分の申告書に{o}年分に生じた損失を翌年以後に繰り越す記載がある（{older}）")
            continue
        _require(rets, range(o, y - 1), c, law)
        c.value += amount
        c.by_year[o] = c.by_year.get(o, 0) + amount
    return c


def carried_casualty_loss(ctx: YearContext, rets: Mapping[int | None, list[Mapping[str, Any]]]) -> Carried:
    """所法71①②・所令204①：前年以前3年内に生じた雑損失の繰り越す額（前年の申告書の記載）。"""
    return _carried_from_last_return(
        ctx, rets, "casualty_loss_carryforward", "所法71②", "3年を超える：特定非常災害の5年の繰越（所法71の2）は後の段：D22 S12"
    )


def carried_listed_loss(ctx: YearContext, rets: Mapping[int | None, list[Mapping[str, Any]]]) -> Carried:
    """措法37の12の2⑤⑦：前年以前3年内に生じた上場株式等に係る譲渡損失の繰り越す額（前年の申告書の記載）。"""
    return _carried_from_last_return(ctx, rets, "listed_stock_loss_carryforward", "措法37の12の2⑦", "3年を超えて繰り越す記載で、矛盾")


# ---------------------------------------------------------------------------
# 選択.株式等の申告（損益通算・繰越控除の適用）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Index:
    """年分の記録の索引（人ごとに記録を走査し直さない：人数 × 記録数にしない）。"""

    kinds: Mapping[str, frozenset[str]]  # 記録の種類 → その年分に記録がある人
    returns: Mapping[str, Mapping[int | None, list[Mapping[str, Any]]]]  # 人 → 年分 → 申告書
    stock_fields: Mapping[str, frozenset[str]]  # 人 → 選択.株式等の申告の value にある欄
    carryback_choosers: frozenset[str]  # その年分の選択.損失申告と繰戻しがある人


def _index(ctx: YearContext) -> _Index:
    kinds: dict[str, frozenset[str]] = {}
    for k in (*STOCK_RECORDS, *LOSS_MATERIAL):
        kinds[k] = frozenset(p for r in ctx.records(k) if overlaps_year(r.get("when"), ctx.year) for p in r["roles"].values())
    returns: dict[str, dict[int | None, list[Mapping[str, Any]]]] = {}
    for rec in ctx.records("filed_document"):
        a = rec["attributes"]
        if a["document_type"] in RETURN_TYPES and rec["roles"].get("filer") is not None:
            returns.setdefault(rec["roles"]["filer"], {}).setdefault(a.get("tax_year"), []).append(rec)
    fields: dict[str, set[str]] = {}
    for c in ctx.choices(STOCK_CHOICE):
        if overlaps_year(c.get("when"), ctx.year):
            fields.setdefault(c["subject"]["person"], set()).update(c["value"])
    choosers = frozenset(c["subject"]["person"] for c in ctx.choices(CARRYBACK_CHOICE) if overlaps_year(c.get("when"), ctx.year))
    return _Index(kinds, returns, {k: frozenset(v) for k, v in fields.items()}, choosers)


def _has_records(idx: _Index, person: str, kinds: tuple[str, ...]) -> bool:
    return any(person in idx.kinds[k] for k in kinds)


def _has_choice(idx: _Index, person: str, field_name: str) -> bool:
    return field_name in idx.stock_fields.get(person, frozenset())


def offset_relevant(ctx: YearContext, person: str, idx: _Index | None = None) -> bool:
    """損益通算（措法37の12の2①）が値を変えうる人：譲渡の記録と配当の記録がある（又はこの選択がある）。"""
    i = idx if idx is not None else _index(ctx)
    return _has_choice(i, person, "loss_offset") or (
        _has_records(i, person, ("security_sale", "brokerage_annual")) and _has_records(i, person, ("dividend", "brokerage_annual"))
    )


def carry_relevant(ctx: YearContext, person: str, idx: _Index | None = None) -> bool:
    """繰越控除（措法37の12の2⑤）が値を変えうる人：繰り越された譲渡損失があり、上場株式等の記録がある（又はこの選択がある）。"""
    i = idx if idx is not None else _index(ctx)
    if _has_choice(i, person, "carryforward"):
        return True
    if not _has_records(i, person, STOCK_RECORDS):
        return False
    c = carried_listed_loss(ctx, i.returns.get(person, {}))
    return c.value > 0 or bool(c.reasons)


def _slots(field_name: str, keyer: Any, relevant: Any, title: str) -> Any:
    def slots(ctx: YearContext) -> Iterator[DecisionSlot]:
        idx = _index(ctx)
        for p in ctx.persons:
            if relevant(ctx, p, idx):
                yield DecisionSlot(
                    key=keyer(p),
                    target={"person": p, "選択の項目": field_name, "説明": title},
                    matches=lambda rec, p=p: rec["subject"]["person"] == p and field_name in rec["value"],
                    candidates=BOOL_CANDIDATES,
                )

    return slots


def _carryback_slots(kind_label: str, candidates: Any) -> Any:
    def slots(ctx: YearContext) -> Iterator[DecisionSlot]:
        idx = _index(ctx)
        for p in ctx.persons:
            if carryback_relevant(ctx, p, idx):
                yield DecisionSlot(
                    key=p,
                    target={"person": p, "tax_year": ctx.year, "説明": kind_label},
                    matches=lambda rec, p=p: rec["subject"]["person"] == p,
                    candidates=candidates,
                )

    return slots


def carryback_relevant(ctx: YearContext, person: str, idx: _Index | None = None) -> bool:
    """繰戻しが値を変えうる人：繰戻しの選択があるか、純損失が生じうる業務の記録があり前年分の課税総所得金額の記載がある。"""
    i = idx if idx is not None else _index(ctx)
    if person in i.carryback_choosers:
        return True
    if not _has_records(i, person, LOSS_MATERIAL):
        return False
    rets = i.returns.get(person, {}).get(ctx.year - 1, [])
    return any(it["amount"] > 0 for r in rets for it in _items(r, "taxable_income_total"))


# ---------------------------------------------------------------------------
# 前々年分への繰戻し（所法140⑤・141④、所令272）
# ---------------------------------------------------------------------------
#
# 中間表現の読み（README §3・§4）：
# - 事実：事業の全部の譲渡又は廃止は blue_return_procedure の business_transfer_or_closure（on がその年）、死亡は人の death_on（その年）。
#   事業の全部の相当期間の休止・重要部分の譲渡（所令272①）は 判断.事業の休止・重要部分の譲渡（その年分）。判断の値は所令272① の
#   「繰越控除を受けることが困難となると認められる」までを含めた判断と読む。
# - 選択.損失申告と繰戻し の second_prior_year_carryback_amount：前々年分に繰り戻す額。額を書くことは、所法140⑤・141④ の期限
#   （その年分の確定申告期限）までに還付を請求することを表す（請求は納税者の選択で、期限内の請求かは別の語彙がない）。
# - 事実（廃止等・死亡）か休止等の判断があって選択が未入力なら、「繰り戻さない」「全額」の候補で評価する（D22 S20）。
#   事実がなく、選択に額が書かれ判断が未入力なら、判断の候補の全部で評価する（D21 R6）。どちらもない人は請求がないものとする
#   （値0。所令272① の事実と請求の意思のどちらの記録もないため。入力すれば評価する）。
# - 繰り戻した額は、その年分の純損失の繰越控除（所法70①）の対象から除く（所法70① かっこ書の「第百四十二条第二項の規定により還付を
#   受けるべき金額の計算の基礎となつたもの」）。繰越控除で控除した額は繰り戻せない（所法140⑤ かっこ書）ので、選択の額は前年の純損失の
#   残り（前年分の申告書の net_loss_total − net_loss_carryback）を限度にし、残りを繰越控除に回す。


def second_key(person: str) -> str:
    return f"{person}:前々年分への繰戻し"


def _y1_loss(rets: Mapping[int | None, list[Mapping[str, Any]]], year: int) -> tuple[Mapping[str, Any] | None, int, int]:
    """(前年分の申告書, 前年に生じた純損失の金額, そのうち前々年分に繰り戻した額〔所法140①〕)。申告書が1件でなければ (None, 0, 0)。"""
    recs = rets.get(year - 1, [])
    if len(recs) != 1:
        return None, 0, 0
    r = recs[0]
    gen = sum(it["amount"] for it in _items(r, "net_loss_total") if it.get("origin_tax_year", year - 1) == year - 1)
    back = sum(it["amount"] for it in _items(r, "net_loss_carryback") if it.get("origin_tax_year", year - 1) == year - 1)
    return r, gen, back


def _event_fact(ctx: YearContext, person: str) -> tuple[str | None, tuple[str, ...]]:
    """その年に生じた所法140⑤ の事業の全部の譲渡・廃止（記録）か、所法141④ の死亡。なければ (None, ())。"""
    for r in ctx.records("blue_return_procedure"):
        if (
            r["roles"].get("person") == person
            and r["attributes"]["procedure"] == "business_transfer_or_closure"
            and int(str(r["when"]["on"])[:4]) == ctx.year
        ):
            return "business_transfer_or_closure", (r["id"],)
    death = ctx.death_on(person)
    if death is not None and death.year == ctx.year:
        return "death", ()
    return None, ()


def _entered_suspension(ctx: YearContext, person: str) -> list[Mapping[str, Any]]:
    return [
        j for j in ctx.judgments(SUSPENSION_JUDGMENT) if j["subject"]["person"] == person and overlaps_year(j.get("when"), ctx.year)
    ]


def _entered_second(ctx: YearContext, person: str) -> list[Mapping[str, Any]]:
    return [
        c
        for c in ctx.choices(CARRYBACK_CHOICE)
        if c["subject"]["person"] == person and overlaps_year(c.get("when"), ctx.year) and SECOND_FIELD in c["value"]
    ]


def second_relevant(ctx: YearContext, person: str, idx: _Index | None = None) -> bool:
    """前々年分への繰戻しの選択が要る人：前年分の申告書に純損失の金額があり、廃止等・死亡の事実、休止等の判断、又は選択の額の記載がある。"""
    i = idx if idx is not None else _index(ctx)
    _, gen, _ = _y1_loss(i.returns.get(person, {}), ctx.year)
    if gen <= 0:
        return False
    if _event_fact(ctx, person)[0] is not None or _entered_second(ctx, person):
        return True
    return any(j["value"] in SUSPENSION_EVENTS for j in _entered_suspension(ctx, person))


def suspension_relevant(ctx: YearContext, person: str, idx: _Index | None = None) -> bool:
    """休止等の判断が要る人：繰り戻す額を選び（又は判断を入力し）、廃止等・死亡の事実がない人。"""
    if not second_relevant(ctx, person, idx) or _event_fact(ctx, person)[0] is not None:
        return False
    return bool(_entered_suspension(ctx, person)) or any(c["value"][SECOND_FIELD] > 0 for c in _entered_second(ctx, person))


@dataclass
class Second:
    """前々年分への繰戻しの入力。reasons_all は繰り戻す額そのものが決まらない（繰越控除の入力も対象外）、
    reasons_refund は還付請求額だけが決まらない、out_of_range は範囲外（山林所得）。"""

    amount: int = 0
    taxable: int = 0
    retirement: int = 0
    after_credits: int = 0
    prior_back: int = 0
    record_ids: set[str] = field(default_factory=set)
    states: set[Any] = field(default_factory=set)
    reasons_all: list[str] = field(default_factory=list)
    reasons_refund: list[str] = field(default_factory=list)
    out_of_range: str | None = None


def second_prior(ctx: YearContext, person: str, rets: Mapping[int | None, list[Mapping[str, Any]]], idx: _Index | None = None) -> Second:
    """所法140⑤・141④・所令272②：その年の前年の純損失を前々年分に繰り戻す額と、前々年分の記載。"""
    s = Second()
    y = ctx.year
    if not second_relevant(ctx, person, idx):
        return s
    d = ctx.decision(CARRYBACK_CHOICE, second_key(person))
    s.record_ids |= set(d.record_ids)
    s.states |= set(d.states)
    chosen = d.value
    if type(chosen) is not int or chosen < 0 or chosen > INT32_MAX:
        s.reasons_all.append("前々年分へ繰り戻す純損失の金額（second_prior_year_carryback_amount）が0以上の int32 の範囲の整数でない")
        return s
    if chosen == 0:
        return s
    kind, ids = _event_fact(ctx, person)
    s.record_ids |= set(ids)
    if kind is None:
        j = ctx.decision(SUSPENSION_JUDGMENT, person)
        s.record_ids |= set(j.record_ids)
        s.states |= set(j.states)
        if j.value not in SUSPENSION_EVENTS:
            return s  # 所令272① の事実がない：前々年分へは繰り戻せない（額は繰越控除に残る）
    r1, gen, back1 = _y1_loss(rets, y)
    if r1 is None:
        s.reasons_all.append(f"{y - 1}年分の申告書の記録が1件に決まらない（前年の純損失の金額：所法140⑤・141④）")
        return s
    s.record_ids.add(r1["id"])
    rest = gen - back1
    if rest <= 0:
        return s
    for t in (y - 1, y - 2):
        ok, bids = blue_evidence(ctx, person, t)
        s.record_ids |= set(bids)
        if not ok:
            s.reasons_all.append(
                f"{t}年分が青色申告書か記録から決まらない（所法140⑤・141④ は前年分・前々年分の青色申告書が要件。承認の通知で first_tax_year が"
                f"{t}以前のものがあり、却下・取消し・取りやめの記録がないときだけ青色とする）"
            )
    c = Carried()
    r2 = _one(rets, y - 2, c)
    if r2 is None:
        s.reasons_all.append(c.reasons[0] if c.reasons else f"{y - 2}年分の申告書の記録がない（所法140⑤・141④ の前々年分の青色申告書）")
        s.record_ids |= c.record_ids
        return s
    s.record_ids.add(r2["id"])
    s.amount = min(chosen, rest)
    if not _items(r2, "taxable_income_total") or not _items(r2, "income_tax_after_credits"):
        s.reasons_refund.append(
            f"{y - 2}年分の申告書に課税総所得金額（taxable_income_total）又は税額控除後の所得税の額（income_tax_after_credits）の記載がない（所令272②）"
        )
    s.taxable = sum(it["amount"] for it in _items(r2, "taxable_income_total"))
    s.after_credits = sum(it["amount"] for it in _items(r2, "income_tax_after_credits"))
    s.retirement = sum(it["amount"] for it in _items(r2, "taxable_retirement_income"))
    s.prior_back = back1
    timber = sum(it["amount"] for it in _items(r2, "taxable_timber_income"))
    stated = bool(_items(r2, "taxable_retirement_income")) and bool(_items(r2, "taxable_timber_income"))
    if s.amount + back1 > s.taxable:
        if timber > 0:
            s.out_of_range = (
                f"前々年分へ繰り戻す純損失の金額が{y - 2}年分の課税総所得金額を超え、{y - 2}年分に課税山林所得金額がある。残りはまず課税山林所得金額から"
                "控除する（所令272②・271①三）が、山林所得は範囲外（D20・SCOPE §4）"
            )
        elif not stated:
            s.reasons_refund.append(
                f"前々年分へ繰り戻す純損失の金額が{y - 2}年分の課税総所得金額を超える。残りを控除する課税山林所得金額・課税退職所得金額（所令272②・271①三）"
                f"の記載（taxable_timber_income・taxable_retirement_income。ないなら0と書く）が{y - 2}年分の申告書にない"
            )
    if y - 2 < SECOND_RATE_FROM:
        s.reasons_refund.append(
            f"{y - 2}年分（前々年分）の所得税法第89条第1項の税率の表の版が docs に記録されていない（記録は令和5年分〜令和8年分：所令272② の所得税の額）"
        )
    if min(s.taxable, s.after_credits, s.retirement, s.prior_back) < 0 or max(s.taxable, s.after_credits, s.retirement, s.prior_back) > INT32_MAX:
        s.reasons_refund.append(f"{y - 2}年分の申告書・{y - 1}年分の繰戻しの記載が負か int32 の範囲の外")
    return s


def _second_choice_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    idx = _index(ctx)
    for p in ctx.persons:
        if second_relevant(ctx, p, idx):
            yield DecisionSlot(
                key=second_key(p),
                target={"person": p, "tax_year": ctx.year, "選択の項目": SECOND_FIELD, "説明": "前年の純損失の前々年分への繰戻し（所法140⑤・141④）"},
                matches=lambda rec, p=p: rec["subject"]["person"] == p and SECOND_FIELD in rec["value"],
                candidates=CARRYBACK_CANDIDATES,
            )


def _suspension_slots(ctx: YearContext) -> Iterator[DecisionSlot]:
    idx = _index(ctx)
    for p in ctx.persons:
        if suspension_relevant(ctx, p, idx):
            yield DecisionSlot(
                key=p,
                target={"person": p, "tax_year": ctx.year, "説明": "事業の全部の相当期間の休止又は重要部分の譲渡（所令272①）"},
                matches=lambda rec, p=p: rec["subject"]["person"] == p,
                candidates=SUSPENSION_CANDIDATES,
            )


DECISIONS = (
    DecisionSpec(
        CARRYBACK_CHOICE,
        _carryback_slots("純損失の繰戻し（所法140）", CARRYBACK_CANDIDATES),
        value_of=lambda rec: rec["value"].get("carryback_amount", 0),
    ),
    DecisionSpec(CARRYBACK_CHOICE, _second_choice_slots, value_of=lambda rec: rec["value"][SECOND_FIELD]),
    DecisionSpec(SUSPENSION_JUDGMENT, _suspension_slots),
    DecisionSpec(PLAN_JUDGMENT, _carryback_slots("その年分の青色申告書の提出期限までの提出（所法140④）", PLAN_CANDIDATES)),
    DecisionSpec(
        STOCK_CHOICE,
        _slots("loss_offset", offset_key, offset_relevant, "上場株式等に係る譲渡損失の損益通算の適用（措法37の12の2①③）"),
        value_of=lambda rec: rec["value"]["loss_offset"],
    ),
    DecisionSpec(
        STOCK_CHOICE,
        _slots("carryforward", carry_key, carry_relevant, "上場株式等に係る譲渡損失の繰越控除の適用（措法37の12の2⑤⑦）"),
        value_of=lambda rec: rec["value"]["carryforward"],
    ),
)


# ---------------------------------------------------------------------------
# build_inputs
# ---------------------------------------------------------------------------


def _set_carried(out: ModuleInputs, var: str, person: str, c: Carried, states: Any = (), basis: Any = ()) -> None:
    ids = tuple(sorted(c.record_ids))
    reasons = list(dict.fromkeys(c.reasons))
    if not reasons and c.value > INT32_MAX:
        reasons.append("繰り越された損失の合計が int32 の上限を超える（OpenFisca に渡さない）")
    out.set(var, person, 0 if reasons else c.value, ids, states, basis=basis)
    if reasons:
        out.exclude(person, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "／".join(reasons), ids), var)


#: 繰り越された損失の生じた年分ごとの内訳の入力（3年前・2年前・前年の順。第四表（二）の年分 A・B・C。2026-11-12：filing.py）。
V_NET_BY_YEAR = (
    "所得税_3年前の年分に生じた繰り越された純損失の金額",
    "所得税_2年前の年分に生じた繰り越された純損失の金額",
    "所得税_前年分に生じた繰り越された純損失の金額",
)
V_CASUALTY_BY_YEAR = (
    "所得税_3年前の年分に生じた繰り越された雑損失の金額",
    "所得税_2年前の年分に生じた繰り越された雑損失の金額",
    "所得税_前年分に生じた繰り越された雑損失の金額",
)
V_LISTED_BY_YEAR = (
    "所得税_3年前の年分に生じた繰り越された上場株式等の譲渡損失の金額",
    "所得税_2年前の年分に生じた繰り越された上場株式等の譲渡損失の金額",
    "所得税_前年分に生じた繰り越された上場株式等の譲渡損失の金額",
)


def _less_by_year(c: Carried, year: int, amount: int) -> None:
    """前々年分に繰り戻した額（前年分の純損失：所法140⑤）を、前年分に生じた分から、足りなければ新しい年分から順に除く。"""
    rest = amount
    for o in range(year - 1, year - 1 - CARRY_YEARS, -1):
        d = min(rest, c.by_year.get(o, 0))
        if d:
            c.by_year[o] -= d
            rest -= d


def _set_by_year(out: ModuleInputs, variables: tuple[str, str, str], person: str, c: Carried, year: int, states: Any = (), basis: Any = ()) -> None:
    """繰り越された損失の生じた年分ごとの内訳（合計の入力と同じ由来。合計が対象外なら内訳も対象外）。"""
    ids = tuple(sorted(c.record_ids))
    reasons = list(dict.fromkeys(c.reasons))
    if not reasons and c.value > INT32_MAX:
        reasons.append("繰り越された損失の合計が int32 の上限を超える（OpenFisca に渡さない）")
    for var, origin in zip(variables, range(year - CARRY_YEARS, year)):
        out.set(var, person, 0 if reasons else c.by_year.get(origin, 0), ids, states, basis=basis)
        if reasons:
            out.exclude(person, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "／".join(reasons), ids), var)


def _carryback_inputs(out: ModuleInputs, ctx: YearContext, p: str, rets: Mapping[int | None, list[Mapping[str, Any]]], idx: _Index) -> None:
    """繰戻しの入力（前年分の記載・選択）。繰戻しが値を変えない人は0・偽。繰り戻す額が正のときだけ、前年分の記載が足りない入力を対象外にする。"""
    relevant = carryback_relevant(ctx, p, idx)
    chosen: Any = 0
    chosen_ids: tuple[str, ...] = ()
    chosen_states: Any = frozenset()
    timely = False
    timely_ids: tuple[str, ...] = ()
    timely_states: Any = frozenset()
    reasons: dict[str, str] = {}
    if relevant:
        d = ctx.decision(CARRYBACK_CHOICE, p)
        chosen, chosen_ids, chosen_states = d.value, d.record_ids, d.states
        if type(chosen) is not int or chosen < 0 or chosen > INT32_MAX:
            reasons[V_CHOSEN_BACK] = "繰り戻す純損失の金額が int32 の範囲の外（OpenFisca に渡さない）"
            chosen = 0
        plan = ctx.decision(PLAN_JUDGMENT, p)
        timely_ids, timely_states = plan.record_ids, plan.states
        within = plan.value.get("within_deadline") if isinstance(plan.value, Mapping) else None
        if within is None:
            reasons[V_TIMELY] = "計画.申告の方法と時期に within_deadline がなく、期限内に提出するか（所法140④）が決まらない"
        else:
            timely = bool(within)
    c = Carried()
    last = _one(rets, ctx.year - 1, c)
    taxable, after, blue = 0, 0, False
    retirement, timber, stated = 0, 0, False
    ids: tuple[str, ...] = ()
    if last is not None:
        ids = (last["id"],)
        taxable = sum(it["amount"] for it in _items(last, "taxable_income_total"))
        after = sum(it["amount"] for it in _items(last, "income_tax_after_credits"))
        retirement = sum(it["amount"] for it in _items(last, "taxable_retirement_income"))
        timber = sum(it["amount"] for it in _items(last, "taxable_timber_income"))
        stated = bool(_items(last, "taxable_retirement_income")) and bool(_items(last, "taxable_timber_income"))
        ok, blue_ids = blue_evidence(ctx, p, ctx.year - 1)
        blue = ok
        ids = tuple(sorted(set(ids) | set(blue_ids)))
    if chosen > 0:
        problem = None
        if last is None:
            problem = f"{ctx.year - 1}年分の申告書の記録が1件に決まらない（ない、又は複数）。繰戻しの前年分の記載（所法140①④）が足りない"
        elif not blue:
            problem = f"{ctx.year - 1}年分が青色申告書か（所法140④）が記録から決まらない"
        elif not _items(last, "taxable_income_total") or not _items(last, "income_tax_after_credits"):
            problem = f"{ctx.year - 1}年分の申告書に課税総所得金額（taxable_income_total）又は税額控除後の所得税の額（income_tax_after_credits）の記載がない"
        if problem:
            for v in (V_PREV_TAXABLE, V_PREV_TAX, V_PREV_BLUE, V_PREV_RET, V_PREV_TIMBER, V_PREV_RET_STATED):
                reasons[v] = problem
    values = {
        V_PREV_TAXABLE: taxable, V_PREV_TAX: after, V_PREV_BLUE: blue, V_PREV_RET: retirement, V_PREV_TIMBER: timber, V_PREV_RET_STATED: stated,
    }
    for var, val in values.items():
        safe = val if type(val) is bool or 0 <= val <= INT32_MAX else 0
        if safe is not val and var not in reasons:
            reasons[var] = "前年分の申告書の記載が int32 の範囲の外（OpenFisca に渡さない）"
        out.set(var, p, safe, ids)
    out.set(V_CHOSEN_BACK, p, chosen, chosen_ids, chosen_states)
    out.set(V_TIMELY, p, timely, timely_ids, timely_states)
    for var, why in reasons.items():
        out.exclude(p, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, why, ids + tuple(chosen_ids)), var)


def _second_inputs(out: ModuleInputs, p: str, s: Second) -> None:
    """前々年分への繰戻しの入力。値は繰り戻す額が正で、繰り戻す額が決まるときだけ入れる（それ以外は0：還付請求額も0）。"""
    ids = tuple(sorted(s.record_ids))
    ok = s.amount > 0 and not s.reasons_all
    values = {
        V2_BACK: s.amount if ok else 0,
        V2_TAXABLE: s.taxable if ok else 0,
        V2_RET: s.retirement if ok else 0,
        V2_TAX: s.after_credits if ok else 0,
        V2_PRIOR: s.prior_back if ok else 0,
    }
    reasons = list(dict.fromkeys(s.reasons_all + (s.reasons_refund if ok else [])))
    for var, val in values.items():
        out.set(var, p, val if 0 <= val <= INT32_MAX else 0, ids, s.states)
    if reasons:
        for var in V2_VARIABLES:
            out.exclude(p, OutOfScopeReason(OutOfScopeCategory.NOT_IMPLEMENTED, "／".join(reasons), ids), var)
    elif ok and s.out_of_range:
        for var in V2_VARIABLES:
            out.exclude(p, OutOfScopeReason(OutOfScopeCategory.OUT_OF_RANGE, s.out_of_range, ids), var)


def build_inputs(ctx: YearContext) -> ModuleInputs:
    out = ModuleInputs()
    idx = _index(ctx)
    for p in ctx.persons:
        rets = idx.returns.get(p, {})
        second = second_prior(ctx, p, rets, idx)
        net = carried_net_loss(ctx, p, rets)
        if second.amount or second.reasons_all:
            net.record_ids |= second.record_ids
            net.reasons.extend(second.reasons_all)
            if not net.reasons:  # 前々年分に繰り戻した額は繰越控除の対象から除く（所法70① かっこ書）
                net.value = max(0, net.value - second.amount)
                _less_by_year(net, ctx.year, second.amount)
        touched = bool(second.amount or second.reasons_all)
        _set_carried(out, V_NET, p, net, second.states if touched else (), (SECOND_PRIOR_RULE,) if second.amount else ())
        _set_by_year(out, V_NET_BY_YEAR, p, net, ctx.year, second.states if touched else (), (SECOND_PRIOR_RULE,) if second.amount else ())
        _second_inputs(out, p, second)
        casualty = carried_casualty_loss(ctx, rets)
        _set_carried(out, V_CASUALTY, p, casualty)
        _set_by_year(out, V_CASUALTY_BY_YEAR, p, casualty, ctx.year)
        listed_loss = carried_listed_loss(ctx, rets)
        _set_carried(out, V_LISTED, p, listed_loss)
        _set_by_year(out, V_LISTED_BY_YEAR, p, listed_loss, ctx.year)
        _carryback_inputs(out, ctx, p, rets, idx)
        for var, relevant, key in ((V_OFFSET, offset_relevant, offset_key(p)), (V_CARRY, carry_relevant, carry_key(p))):
            if relevant(ctx, p, idx):
                d = ctx.decision(STOCK_CHOICE, key)
                out.set(var, p, bool(d.value), d.record_ids, d.states)
            else:  # 上場株式等の記録がない人：上場株式等の所得は0で、適用の有無で値が変わらない
                out.set(var, p, False)
    return out

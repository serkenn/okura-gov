"""規則モジュール income_kinds：不動産所得の区分の材料（判断.不動産の区分の材料 J-21）と計上の方法（選択.不動産所得の計上 C-10）。

2026-11-12（語彙の全種類を規則モジュールが使うようにした作業。IK-116〜IK-119・IK-131）。原文は docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md
（§1.2 所令79、§1.3 基通27−2・27−3、§2.2 基通36−5〜36−7・直所2−78、§4.1 所法69②・所令178①二、§4.3 措法41の4・措令26の6②・措通41の4−3）、
仮説 docs/hypotheses/20261109_round2b_fudosan-calculation-model.md H1〜H3・H10。

判断.不動産の区分の材料（対象 record_id：rental_property・lease・rent_flow）：
- custodial_parking・simple_facility が真：自己の責任において他人の物を保管する駐車場（基通27−2）・バンガロー等の簡易な施設（基通27−3）の所得は
  事業所得又は雑所得。その貸付けの賃料が rent_flow（不動産所得）で記録されていれば入力の矛盾（業務の売上 business_receipt として業務に書く）。
  property_type が parking の物件の賃料で、custodial_parking の判断がなければ、両方で評価して未確定（判断。D21 R6）。
- villa_purpose：別荘等（所令178①二。所法69② の損益通算の制限）か。物件の held_as_villa の代わりに使う（両方あって違えば入力の矛盾）。
- land_market_value：借地権・地役権の設定の対価（rent_flow の key_money・renewal_fee・other）が土地の価額の10分の5を超えれば譲渡所得
  （所令79①一。土地建物等の譲渡は範囲外：D20）。所令79①二（建物の一部の所有を目的とする設定）・三と所令80 の特別の経済的利益は語彙がない。

選択.不動産所得の計上（when.tax_year、対象 record_id、rule、apply）：
- period_matching（直所2−78）：選んだ年分の賃貸料（rent・common_service_fee。頭金・権利金・名義書換料・更新料・礼金等は含まない：同 1（注））を、
  対象の期間（rent_flow.covered_period）のうちその年分の部分で数える。事業的規模でなければ1年以内の期間の賃貸料だけ（同 2）。
  帳簿の要件（同 1(1)〜(3)）は選択の記録が満たす旨の申出と読む。その年分の賃貸料の全部が選択の対象でなければ入力の矛盾（同 1(2)「全部について」）。
  年分をまたぐ受取の割当て（`_destination`）：対象の期間の年分が期間対応の年分ならその年分（前払の受取の年分が支払日による年分なら受取の年分：
  同 3(1)（注）の「11か月分」）、ほかは受取の年分。期間対応をやめた年分の前受の扱い（同 3 の調整）は docs に原文がないので、候補（受取の年分・期間の年分）で
  未確定（一次情報）。年をまたぐ期間の按分は、月の初日から月の末日までの期間なら月数、ほかは日数で行い、日数の按分と1円未満の端数は一次情報がないので未確定。
- loan_interest_allocation（措令26の6②）：借入れ（loan）の負債の額をまず建物、次に土地等の取得の対価に充てたものとして、土地等の負債の利子
  ＝利子×土地等に充てた負債の額／負債の額（措通41の4−3）。一の契約（rental_property.acquisition_contract が同じ）で建物とともに取得した土地等に限る。
  割合の1円未満の端数は一次情報がない（仮説 H3）ので未確定。
- deposit_recognition_proviso（基通36−6 ただし書：引渡しを要する頭金・権利金等を契約の効力発生の日で計上）：引渡しの日・効力発生の日の語彙がない
  （rent_flow の when は取引の日）。選んだ人の頭金・権利金等の年分を、記録の日の年分と効力発生の日の年分の候補で未確定（事実）にする。
- 選択が false・未入力なら原則（基通36−5・36−6 本文。記録の日の年分）。候補で評価しない理由：期間対応は帳簿の要件を満たして継続する方法で、
  記録がないときに要件を満たすかは入力から決まらない（README）。
"""

from __future__ import annotations

import calendar
import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...registry import YearContext
from ...result import Means, Split
from .common import add_months, undetermined

K_RENT_MATERIAL = "判断.不動産の区分の材料"
K_RENT_TIMING = "選択.不動産所得の計上"
K_RENT_SCALE = "判断.不動産の事業的規模"
RULE_PERIOD = "period_matching"
RULE_LOAN = "loan_interest_allocation"
RULE_DEPOSIT = "deposit_recognition_proviso"
PERIOD_FLOWS = ("rent", "common_service_fee")
LUMP_FLOWS = ("key_money", "renewal_fee", "other")
LAND_TYPES = frozenset({"land", "parking"})
RENTAL_KINDS = (("rental_property", "owner"), ("lease", "lessor"), ("rent_flow", "recipient"), ("rental_inventory", "owner"))
TARGET_ROLES = {"rental_property": "owner", "lease": "lessor", "rent_flow": "recipient", "loan": "borrower"}
by_id_kinds = frozenset({"rental_property", "lease", "rent_flow"})
#: 規定ごとの対象の記録の種類
RULE_TARGETS = {
    RULE_PERIOD: frozenset({"rental_property", "lease", "rent_flow"}),
    RULE_LOAN: frozenset({"loan"}),
    RULE_DEPOSIT: frozenset({"rent_flow"}),
}

CUSTODIAL_REASON = (
    "入力の矛盾：判断.不動産の区分の材料 で、保管責任のある駐車場（基通27−2）か簡易な施設（基通27−3）とした貸付けの賃料が、不動産所得の賃料（rent_flow）で"
    "記録されている（事業所得又は雑所得：業務の売上 business_receipt として業務 business_id に記録する）"
)
VILLA_CONFLICT_REASON = "入力の矛盾：物件の held_as_villa と 判断.不動産の区分の材料 の villa_purpose が違う"
MATERIAL_TARGET_REASON = "入力の矛盾：判断.不動産の区分の材料 の対象が賃貸物件・賃貸借契約・賃料の記録でない（別荘の目的は賃貸物件にだけ書く）"
LAND_TRANSFER_REASON = (
    "借地権・地役権の設定の対価が土地の価額（判断.不動産の区分の材料 の land_market_value）の10分の5を超え、譲渡所得になる（所法33①・所令79①一）。"
    "土地建物等の譲渡は範囲外（D20）"
)
TIMING_TARGET_REASON = "入力の矛盾：選択.不動産所得の計上 の対象が、選んだ人の賃貸物件・賃貸借契約・賃料・借入れの記録でないか、規定（rule）と記録の種類が合わない"
PERIOD_ALL_REASON = (
    "入力の矛盾：期間対応（直所2−78）は賃貸料の全部について継続して適用する（同 1(2)）が、この年分の賃貸料に選択.不動産所得の計上 の対象でないものがある"
)
PERIOD_MISSING_REASON = "入力の不足：期間対応（直所2−78）を選んだ賃貸料（rent_flow）に対象の期間（attributes.covered_period）がない"
LOAN_ALLOCATION_REASON = (
    "入力の不足・矛盾：措令26の6② を選んだ借入れが、一の契約（rental_property.acquisition_contract）で建物とともに取得した土地等の借入れでないか、"
    "取得の対価（acquisition_cost）・借入れの元本がない、又は利子の支出（business_expense）に借入れ（attributes.loan_id）がない"
)


def _year(d: str) -> int:
    return _dt.date.fromisoformat(d).year


def _person_of(rec: Mapping[str, Any]) -> str | None:
    role = TARGET_ROLES.get(rec["kind"])
    return rec["roles"].get(role) if role else None


def has_rental(ctx: YearContext, pid: str) -> bool:
    """inputs._has_rental と同じ（循環 import を避ける）。"""
    return any(
        r["roles"].get(role) == pid and _overlaps(r.get("when"), ctx.year) for kind, role in RENTAL_KINDS for r in ctx.records(kind)
    )


def _overlaps(when: Mapping[str, Any] | None, year: int) -> bool:
    from ...registry import overlaps_year

    return overlaps_year(when, year)


# ---------------------------------------------------------------------------
# 選択.不動産所得の計上（期間対応：直所2−78）
# ---------------------------------------------------------------------------


@dataclass
class _Person:
    problems: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)
    ids: set[str] = field(default_factory=set)


def _covers(target: Mapping[str, Any], f: Mapping[str, Any], leases: Mapping[str, Mapping[str, Any]]) -> bool:
    a = f["attributes"]
    if target["kind"] == "rent_flow":
        return target["id"] == f["id"]
    if target["kind"] == "lease":
        return a.get("lease_id") == target["id"]
    prop = a.get("property_id") or leases.get(a.get("lease_id", ""), {}).get("attributes", {}).get("property_id")
    return prop == target["id"]


def _portions(f: Mapping[str, Any]) -> tuple[dict[int, Fraction], str]:
    """対象の期間の年分ごとの賃貸料（按分の単位：whole＝1つの年分・months＝月数・days＝日数）。"""
    p = f["attributes"]["covered_period"]
    a = _dt.date.fromisoformat(p["from_on"])
    b = _dt.date.fromisoformat(p.get("to_on") or p["from_on"])
    amount = f["amounts"]["amount"]
    if a.year == b.year:
        return {a.year: Fraction(amount)}, "whole"
    if a.day == 1 and b.day == calendar.monthrange(b.year, b.month)[1]:
        total = (b.year - a.year) * 12 + b.month - a.month + 1
        out: dict[int, Fraction] = {}
        for y in range(a.year, b.year + 1):
            m0 = a.month if y == a.year else 1
            m1 = b.month if y == b.year else 12
            out[y] = Fraction(amount * (m1 - m0 + 1), total)
        return out, "months"
    total_days = (b - a).days + 1
    out = {}
    for y in range(a.year, b.year + 1):
        s = max(a, _dt.date(y, 1, 1))
        e = min(b, _dt.date(y, 12, 31))
        out[y] = Fraction(amount * ((e - s).days + 1), total_days)
    return out, "days"


def _long(f: Mapping[str, Any]) -> bool:
    """対象の期間が1年を超えるか（直所2−78 2：事業的規模でなければ1年以内の期間に係る賃貸料だけ）。"""
    p = f["attributes"]["covered_period"]
    a = _dt.date.fromisoformat(p["from_on"])
    b = _dt.date.fromisoformat(p.get("to_on") or p["from_on"])
    return b >= add_months(a, 12)


class RentView:
    """YearContext に、期間対応（直所2−78）を当てた rent_flow を見せる包み（build_inputs の間だけ使う）。

    期間対応を選んだことのある人の賃貸料（rent・common_service_fee）は、この年分に割り当てた額の写し（when.on は受取の年分ならそのまま、
    ほかの年分の受取ならこの年分の12月31日）にし、割り当てない記録は見せない。ほかの記録・人はそのまま。
    """

    def __init__(self, ctx: YearContext) -> None:
        self._ctx = ctx
        self.people: dict[str, _Person] = {}
        self._flows: list[Mapping[str, Any]] | None = None
        self._rental: dict[str, bool] = {}

    def _has_rental(self, pid: str) -> bool:
        if pid not in self._rental:
            self._rental[pid] = has_rental(self._ctx, pid)
        return self._rental[pid]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)

    def records(self, kind: str) -> list[Mapping[str, Any]]:
        if kind != "rent_flow":
            return self._ctx.records(kind)
        if self._flows is None:
            self._flows = self._build()
        return self._flows

    def person(self, pid: str) -> _Person:
        return self.people.setdefault(pid, _Person())

    # 期間対応の選択（人 → 年分 → 対象の記録の一覧）
    def _period_choices(self) -> dict[str, dict[int, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]]:
        ctx = self._ctx
        by_id = {r["id"]: r for k in TARGET_ROLES for r in ctx.records(k)}
        out: dict[str, dict[int, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]] = {}
        for c in ctx.choices(K_RENT_TIMING):
            if c["value"]["rule"] != RULE_PERIOD:
                continue
            target = by_id.get(c["subject"]["record_id"])
            if target is None or target["kind"] not in RULE_TARGETS[RULE_PERIOD]:
                continue  # 対象の誤りは contribute が入力の矛盾にする
            pid = _person_of(target)
            if c["value"]["apply"]:
                out.setdefault(pid, {}).setdefault(c["when"]["tax_year"], []).append((c, target))
            elif c["when"]["tax_year"] == ctx.year:
                self.person(pid).ids.add(c["id"])
        return out

    def _build(self) -> list[Mapping[str, Any]]:
        ctx = self._ctx
        flows = list(ctx.records("rent_flow"))
        choices = self._period_choices()
        if not choices:
            return flows
        leases = {r["id"]: r for r in ctx.records("lease")}
        out: list[Mapping[str, Any]] = []
        Y = ctx.year
        for f in flows:
            pid = f["roles"]["recipient"]
            by_year = choices.get(pid)
            if not by_year or f["attributes"]["flow_type"] not in PERIOD_FLOWS or pid not in ctx.persons or not self._has_rental(pid):
                out.append(f)
                continue
            me = self.person(pid)
            r = _year(f["when"]["on"])

            def matched(y: int, f: Mapping[str, Any] = f) -> list[str]:
                return [c["id"] for c, t in by_year.get(y, []) if _covers(t, f, leases)]

            if Y in by_year and r == Y and not matched(Y):
                me.problems.append((PERIOD_ALL_REASON, (f["id"],)))
            if "covered_period" not in f["attributes"]:
                if matched(r) and r == Y:
                    me.problems.append((PERIOD_MISSING_REASON, (f["id"], *matched(r))))
                if r == Y:
                    out.append(f)
                continue
            if _long(f) and not self._business_scale(pid, me):
                if r == Y:
                    out.append(f)  # 事業的規模でない人の1年を超える期間の賃貸料は支払日による（直所2−78 2）
                continue
            parts, unit = _portions(f)
            here = Fraction(0)
            touched = False
            for c, amt in parts.items():
                dest, open_ = self._destination(c, r, bool(matched(c)), bool(matched(r)))
                if open_ and Y in (c, r):
                    me.splits.append(undetermined(
                        f"一次情報:期間対応をやめた年分の前受の賃貸料:{f['id']}:{c}", Means.PRIMARY_SOURCE,
                        {"person": pid, "record_id": f["id"], "事項": "期間対応（直所2−78）をやめた年分の対象の期間の賃貸料を前の受取の年分と期間の年分のどちらに数えるか（同 3 の調整の原文が docs にない）"},
                        ("受取の年分", "期間の年分"),
                    ))
                if dest == Y:
                    here += amt
                    if c != r:
                        touched = True
                        me.ids |= set(matched(c)) | set(matched(r))
            if r == Y:
                me.ids |= set(matched(r))
                touched = touched or len(parts) > 1
            if touched and unit == "days":
                me.splits.append(undetermined(
                    f"一次情報:期間対応の日数による按分:{f['id']}", Means.PRIMARY_SOURCE,
                    {"person": pid, "record_id": f["id"], "事項": "月の初日から月の末日までの期間でない賃貸料を年分に按分する単位（直所2−78 は貸付期間に対応する部分とだけ書く）"},
                    ("日数で按分", "月数で按分"),
                ))
            if here.denominator != 1:
                me.splits.append(undetermined(
                    f"一次情報:期間対応の按分の端数:{f['id']}", Means.PRIMARY_SOURCE,
                    {"person": pid, "record_id": f["id"], "事項": "期間対応で年分に按分した賃貸料の1円未満の端数（通達に定めがない）"},
                    ("切捨て", "切上げ"),
                ))
            amount = int(here)
            if amount == 0 and not (r == Y and f["amounts"]["amount"] == 0):
                continue
            if r == Y and amount == f["amounts"]["amount"]:
                out.append(f)
                continue
            out.append({**f, "when": {"on": f["when"]["on"] if r == Y else f"{Y}-12-31"}, "amounts": {**f["amounts"], "amount": amount}})
        return out

    @staticmethod
    def _destination(c: int, r: int, m_c: bool, m_r: bool) -> tuple[int, bool]:
        """対象の期間の年分 c・受取の年分 r の賃貸料を数える年分と、一次情報で決まらないか。"""
        if c == r:
            return r, False
        if m_c and not (c > r and not m_r):
            return c, False
        if m_r and c > r and not m_c:
            return r, True  # 期間対応をやめた年分の前受（同 3 の調整の原文がない）：受取の年分の候補で計算して未確定
        return r, False

    def _business_scale(self, pid: str, me: _Person) -> bool:
        d = self._ctx.decision(K_RENT_SCALE, pid)
        me.ids |= set(d.record_ids)
        return bool(d.value)


# ---------------------------------------------------------------------------
# 不動産所得の側への寄与（inputs._business から人ごとに呼ぶ）
# ---------------------------------------------------------------------------


def _materials(ctx: YearContext) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for j in ctx.judgments(K_RENT_MATERIAL):
        out.setdefault(j["subject"]["record_id"], []).append(j)
    return out


def villa_flag(ctx: YearContext, prop: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """物件が別荘等か（判断.不動産の区分の材料 の villa_purpose があればそれ、なければ held_as_villa）と、使った判断の ID。"""
    js = [j for j in _materials(ctx).get(prop["id"], []) if "villa_purpose" in j["value"]]
    if js:
        return bool(js[0]["value"]["villa_purpose"]), (js[0]["id"],)
    return bool(prop["attributes"].get("held_as_villa")), ()


def contribute(ctx: YearContext, pid: str, problems: list[Any], missing: list[Any], ids: set[str], rental_vars: tuple[str, ...]) -> None:
    """判断.不動産の区分の材料 と 選択.不動産所得の計上 の、その人・年分の不動産所得の側の対象外（problems）・未確定（missing）・由来（ids）。"""
    view = ctx if isinstance(ctx, RentView) else None
    if view is not None:
        view.records("rent_flow")
        me = view.people.get(pid)
        if me is not None:
            problems += [(t, rids, rental_vars) for t, rids in me.problems]
            missing += [(sp, rental_vars) for sp in me.splits]
            ids |= me.ids
    every = {r["id"]: r for s in ("relations", "residences", "insurance_memberships", "facts", "assets", "filed_documents") for r in ctx.ir[s]}
    leases = {r["id"]: r for r in ctx.records("lease")}
    flows = [f for f in ctx.records("rent_flow") if f["roles"]["recipient"] == pid and _year(f["when"]["on"]) == ctx.year]
    by_id = {r["id"]: r for k in ("rental_property", "lease", "rent_flow") for r in ctx.records(k)}
    mats = _materials(ctx)
    judged_custodial: set[str] = set()
    for rid, js in sorted(mats.items()):
        target = by_id.get(rid)
        j = js[0]
        if target is None:
            raw = every.get(rid)
            if raw is not None and raw["kind"] not in by_id_kinds and pid in raw.get("roles", {}).values():
                ids.add(j["id"])
                problems.append((MATERIAL_TARGET_REASON, (j["id"], rid), rental_vars))
            continue
        if _person_of(target) != pid:
            continue
        v = j["value"]
        ids.add(j["id"])
        if "villa_purpose" in v:
            if target["kind"] != "rental_property":
                problems.append((MATERIAL_TARGET_REASON, (j["id"],), rental_vars))
            elif "held_as_villa" in target["attributes"] and bool(target["attributes"]["held_as_villa"]) != bool(v["villa_purpose"]):
                problems.append((VILLA_CONFLICT_REASON, (j["id"], rid), rental_vars))
        covered = [f for f in flows if _covers(target, f, leases)]
        if "custodial_parking" in v:
            judged_custodial.add(rid)
        if (v.get("custodial_parking") or v.get("simple_facility")) and covered:
            problems.append((CUSTODIAL_REASON, (j["id"], *(f["id"] for f in covered)), rental_vars))
        if "land_market_value" in v:
            over = [f["id"] for f in covered if f["attributes"]["flow_type"] in LUMP_FLOWS and f["amounts"]["amount"] * 2 > v["land_market_value"]]
            if over:
                problems.append((LAND_TRANSFER_REASON, (j["id"], *over), rental_vars))
    # 駐車場の物件で保管責任の判断がない（D21 R6：両方で評価して未確定）
    for prop in ctx.records("rental_property"):
        if prop["roles"]["owner"] != pid or prop["attributes"]["property_type"] != "parking" or not _overlaps(prop.get("when"), ctx.year):
            continue
        covered = [f for f in flows if _covers(prop, f, leases)]
        if not covered:
            continue
        linked = {prop["id"]} | {lid for lid, l in leases.items() if l["attributes"]["property_id"] == prop["id"]} | {f["id"] for f in covered}
        if linked & judged_custodial:
            continue
        missing.append((undetermined(
            f"判断:駐車場の保管責任:{prop['id']}:{ctx.year}", Means.JUDGMENT,
            {"person": pid, "property_id": prop["id"], "kind": K_RENT_MATERIAL, "入力": "判断.不動産の区分の材料 の custodial_parking（自己の責任において他人の物を保管するか：基通27−2）"},
            ("保管責任なし（不動産所得）", "保管責任あり（事業所得又は雑所得）"),
        ), rental_vars))
    for c in ctx.choices(K_RENT_TIMING):
        if c["when"]["tax_year"] != ctx.year:
            continue
        target = every.get(c["subject"]["record_id"])
        if target is None or pid not in target.get("roles", {}).values():
            continue
        ids.add(c["id"])
        if target["kind"] not in RULE_TARGETS[c["value"]["rule"]] or _person_of(target) != pid:
            problems.append((TIMING_TARGET_REASON, (c["id"], target["id"]), rental_vars))
            continue
        # 基通36−6 ただし書：引渡しの日・効力発生の日の語彙がない
        if c["value"]["rule"] != RULE_DEPOSIT or not c["value"]["apply"]:
            continue
        missing.append((undetermined(
            f"事実:頭金・権利金等の契約の効力発生の日:{c['id']}", Means.FACT,
            {"person": pid, "record_id": target["id"], "入力": "頭金・権利金等の資産の引渡しの日と契約の効力発生の日（基通36−6。中間表現に語彙がない：rent_flow の when は取引の日）"},
            ("記録の日の年分", "効力発生の日の年分"),
        ), rental_vars))


# ---------------------------------------------------------------------------
# 措令26の6②：土地等を取得するために要した負債の利子
# ---------------------------------------------------------------------------


def land_interest_choice(
    ctx: YearContext, pid: str, interest_recs: list[Mapping[str, Any]]
) -> tuple[int, tuple[str, ...], tuple[Split, ...], list[tuple[str, tuple[str, ...]]]] | None:
    """措令26の6② を選んだ借入れがあれば（土地等の負債の利子の額, 由来, 未確定, 対象外）。なければ None。"""
    loans = {r["id"]: r for r in ctx.records("loan")}
    chosen = {}
    problems: list[tuple[str, tuple[str, ...]]] = []
    for c in ctx.choices(K_RENT_TIMING):
        if c["value"]["rule"] != RULE_LOAN or c["when"]["tax_year"] != ctx.year:
            continue
        loan = loans.get(c["subject"]["record_id"])
        if loan is None:
            continue
        if loan["roles"]["borrower"] != pid:
            continue
        if c["value"]["apply"]:
            chosen[loan["id"]] = c["id"]
    if not chosen:
        return None
    props = {r["id"]: r for r in ctx.records("rental_property") if r["roles"]["owner"] == pid}
    ids: set[str] = set(chosen.values()) | set(chosen)
    total = Fraction(0)
    for r in interest_recs:
        lid = r["attributes"].get("loan_id")
        ids.add(r["id"])
        if not lid or lid not in loans:
            problems.append((LOAN_ALLOCATION_REASON, (r["id"],)))
            continue
        loan = loans[lid]
        prop = props.get(loan["attributes"].get("purpose_asset_id", ""))
        if lid not in chosen:
            if prop is not None and prop["attributes"]["property_type"] in LAND_TYPES:
                total += r["amounts"]["amount"]
            continue
        contract = prop["attributes"].get("acquisition_contract") if prop is not None else None
        group = [p for p in props.values() if contract and p["attributes"].get("acquisition_contract") == contract]
        land = [p for p in group if p["attributes"]["property_type"] in LAND_TYPES]
        building = [p for p in group if p["attributes"]["property_type"] not in LAND_TYPES]
        principal = loan["amounts"]["principal"]
        if not land or not building or principal <= 0 or any("acquisition_cost" not in p.get("amounts", {}) for p in group):
            problems.append((LOAN_ALLOCATION_REASON, (chosen[lid], lid)))
            continue
        ids |= {p["id"] for p in group}
        b_cost = sum(p["amounts"]["acquisition_cost"] for p in building)
        l_cost = sum(p["amounts"]["acquisition_cost"] for p in land)
        land_debt = min(l_cost, max(0, principal - b_cost))
        total += Fraction(r["amounts"]["amount"] * land_debt, principal)
    splits: tuple[Split, ...] = ()
    if total.denominator != 1:
        splits = (undetermined(
            f"一次情報:措通41の4−3 の割合の端数:{pid}:{ctx.year}", Means.PRIMARY_SOURCE,
            {"person": pid, "loan_ids": sorted(chosen), "事項": "措通41の4−3 の土地等の負債の利子の割合の1円未満の端数（fudosan §9-3。仮説 H3）"},
            ("切捨て", "切上げ"),
        ),)
    return int(total), tuple(sorted(ids)), splits, problems


__all__ = [
    "K_RENT_MATERIAL",
    "K_RENT_TIMING",
    "RentView",
    "contribute",
    "land_interest_choice",
    "villa_flag",
]

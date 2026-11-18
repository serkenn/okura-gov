"""income_kinds の所法56（生計を一にする親族への対価）・専従者の境目・青色の承認の読みのユニットテスト（入力の段の関数を直接呼ぶ。上流はスタブ）。

期待値の出典：docs/public-sources/20261109_round2b_fudosan-laws-and-nta.md §5.1・§5.2・§9-2（所法56、TA2210）、
docs/public-sources/20261109_round2_aoiro-laws-and-nta.md §1.2（所基通144−1・A1-8）・§4.1（所法57①・所令165〜167）。テストのデータは架空の家庭。
"""

from __future__ import annotations

import unittest
from typing import Any

from okura_core.registry import Decided, ModuleInputs, YearContext, YearWindow
from okura_core.rules.income_kinds.inputs import (
    DECISIONS,
    K_JIGYO,
    K_RENT_SCALE,
    LINK_56_SIDE_REASON,
    V_BIZ_DEP,
    V_BIZ_EXP,
    V_BIZ_REV,
    V_MISC_EXP,
    V_RENT_EXP,
    V_RENT_REV,
    BLUE_APPROVED,
    BLUE_NOT_APPROVED,
    V_FAMILY_SALARY_OUT,
    _business,
    _family_employees,
    _land_interest_by_loan,
    _Sides,
    _villa_by_property,
    blue_state,
)
from okura_core.rules.income_kinds.calc import FILING_EBOOKS, FILING_PAPER, BlueRules, blue_deduction
from okura_core.rules.income_kinds.consumption import INCLUSIVE, CtPlan, tax_expense_by_business
from okura_core.rules.income_kinds.family import K_SEIKEI

from ...support import make_ir, person, system

AT = "2027-02-01T10:00:00+09:00"


def _ctx(ir: dict[str, Any], overrides: dict[tuple[str, str], Any] | None = None, year: int = 2026) -> YearContext:
    """宣言された判断・選択の1か所を全部、overrides か既定（真偽は True、候補があれば最初の候補）で決めた YearContext。"""
    window = YearWindow(parameters_at=lambda on: system().get_parameters_at_instant(str(on)), rounding={"必要経費の1円未満（按分・一括償却・事業専従者控除）": "floor"})
    persons = tuple(p["id"] for p in ir["persons"])
    base = YearContext(ir, year, persons, window=window)
    decided: dict[tuple[str, str], Decided] = {}
    for spec in DECISIONS:
        for slot in spec.slots(base):
            key = (spec.kind, slot.key)
            if overrides and key in overrides:
                value = overrides[key]
            else:
                value = slot.candidates[0].value if slot.candidates else True
            decided[key] = Decided(value, (), frozenset(), True)
    return base.with_decided(decided)


def _family() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    persons = [person("p", "1960-01-01"), person("q", "1990-01-01")]
    relations = [{"id": "r-pc", "kind": "parentage", "roles": {"parent": "p", "child": "q"}, "when": {"on": "1990-01-01"}, "attributes": {"basis": "birth_mother"}}]
    return persons, relations


def _rent_case() -> dict[str, Any]:
    """p が事業（b-p）のために、生計を一にする子 q の部屋を借りて賃料 600,000 を払う。q はその部屋の固定資産税 50,000 を払う。"""
    persons, relations = _family()
    facts = [
        {"id": "b-p", "kind": "business", "roles": {"owner": "p"}, "when": {"from_on": "2020-01-01"}, "attributes": {}},
        {"id": "b-q", "kind": "business", "roles": {"owner": "q"}, "when": {"from_on": "2020-01-01"}, "attributes": {}},
        {"id": "s-1", "kind": "business_receipt", "roles": {"recipient": "p"}, "when": {"on": "2026-05-01"}, "amounts": {"amount": 3_000_000}, "attributes": {"business_id": "b-p"}},
        {"id": "e-1", "kind": "business_expense", "roles": {"payer": "p", "payee": "q"}, "when": {"on": "2026-12-01"}, "amounts": {"amount": 600_000}, "attributes": {"business_id": "b-p", "expense_category": "rent"}},
        {"id": "f-1", "kind": "rent_flow", "roles": {"recipient": "q", "payer": "p"}, "when": {"on": "2026-12-01"}, "amounts": {"amount": 600_000}, "attributes": {"flow_type": "rent", "property_id": "rp-1"}},
        {"id": "e-2", "kind": "business_expense", "roles": {"payer": "q"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 50_000}, "attributes": {"business_id": "b-q", "expense_category": "tax"}},
    ]
    assets = [{"id": "rp-1", "kind": "rental_property", "roles": {"owner": "q"}, "when": {"from_on": "2015-01-01"}, "attributes": {"property_type": "room", "business_id": "b-q"}}]
    return make_ir(persons, facts, relations=relations, assets=assets)


def _value(out: ModuleInputs, var: str, pid: str) -> Any:
    return out.values[(var, pid)]


class Rule56Test(unittest.TestCase):
    def test_business_rent_is_not_expense_and_receiver_cost_moves(self) -> None:
        # 所法56：事業からの対価は必要経費にせず、受取側の対価と必要経費はないものとみなし、受取側の必要経費は支払側の必要経費（fudosan §5.1）
        out = ModuleInputs()
        _business(_ctx(_rent_case(), {(K_JIGYO, "p:b-p"): True, (K_RENT_SCALE, "q"): False}), out)
        self.assertEqual(_value(out, V_BIZ_EXP, "p").value, 50_000)
        self.assertEqual((_value(out, V_RENT_REV, "q").value, _value(out, V_RENT_EXP, "q").value), (0, 0))
        self.assertEqual(out.exclusions, [])
        self.assertEqual(_value(out, V_BIZ_EXP, "p").missing, ())

    def test_gyomu_rent_is_counted_with_reading_split(self) -> None:
        # 業務（雑所得）からの対価：条文（事業）と TA2210（業務）で読みが分かれる（fudosan §9-2）→ 数えた値に未確定の分かれ目
        out = ModuleInputs()
        _business(_ctx(_rent_case(), {(K_JIGYO, "p:b-p"): False, (K_RENT_SCALE, "q"): False}), out)
        self.assertEqual(_value(out, V_MISC_EXP, "p").value, 600_000)
        self.assertEqual(_value(out, V_RENT_REV, "q").value, 600_000)
        self.assertTrue(_value(out, V_MISC_EXP, "p").missing)
        self.assertTrue(_value(out, V_RENT_REV, "q").missing)

    def test_household_rent_from_family_is_ordinary_rental_income(self) -> None:
        # 事業から対価でない家族の賃料（p の業務の支出がない）は通常の不動産所得（所法56 は事業から対価の支払を受ける場合だけ）
        ir = _rent_case()
        ir["facts"] = [f for f in ir["facts"] if f["id"] != "e-1"]
        out = ModuleInputs()
        _business(_ctx(ir, {(K_RENT_SCALE, "q"): False}), out)
        self.assertEqual((_value(out, V_RENT_REV, "q").value, _value(out, V_RENT_EXP, "q").value), (600_000, 50_000))
        self.assertEqual(_value(out, V_RENT_REV, "q").missing, ())


def _employee_ctx(paid: int, monthly: int | None, *, months: tuple[str, str] = ("2026-01-01", "2026-12-31"), biz_from: str = "2020-01-01") -> tuple[YearContext, dict[str, Any]]:
    persons, relations = _family()
    facts = [
        {"id": "b-p", "kind": "business", "roles": {"owner": "p"}, "when": {"from_on": biz_from}, "attributes": {}},
        {"id": "w-1", "kind": "payroll_paid", "roles": {"employer": "p", "recipient": "q"}, "when": {"on": "2026-12-20"}, "amounts": {"amount": paid}, "attributes": {"business_id": "b-p", "pay_type": "family_employee_salary"}},
        {"id": "g-1", "kind": "business_engagement", "roles": {"business_owner": "p", "relative": "q"}, "when": {"from_on": months[0], "to_on": months[1]}, "attributes": {"business_id": "b-p"}},
        {"id": "n-1", "kind": "family_employee_notice", "roles": {"employer": "p", "employee": "q"}, "when": {"on": "2026-03-01"}, "amounts": {"monthly_salary": monthly} if monthly else {}, "attributes": {"notice_type": "initial"}},
        {"id": "pr-1", "kind": "blue_return_procedure", "roles": {"person": "p"}, "when": {"on": "2020-03-01"}, "attributes": {"procedure": "approval_notice", "first_tax_year": 2020}},
    ]
    ir = make_ir(persons, facts, relations=relations)
    return _ctx(ir, {(K_JIGYO, "p:b-p"): True}), facts[1]


class FamilyEmployeeTest(unittest.TestCase):
    def test_excess_over_notice_is_not_expense(self) -> None:
        # 所法57①：届出の金額の範囲内だけ必要経費。超える部分は所法56 で必要経費にしない（以前は対象外）
        ctx, pay = _employee_ctx(1_500_000, 100_000)
        s = _Sides()
        _family_employees(ctx, "p", s, {"b-p": "biz"}, {"b-p": [pay]}, None, {}, ["b-p"])
        self.assertEqual((s.salary["biz"], s.exp["biz"], s.problems), (1_200_000, 0, []))

    def test_not_engaged_over_six_months_is_not_expense(self) -> None:
        # 所令165①本文：6月を超えて専ら従事しない親族への給与は青色事業専従者給与でなく、所法56 で必要経費にしない
        ctx, pay = _employee_ctx(600_000, 100_000, months=("2026-07-01", "2026-12-31"))
        s = _Sides()
        _family_employees(ctx, "p", s, {"b-p": "biz"}, {"b-p": [pay]}, None, {}, ["b-p"])
        self.assertEqual((s.salary["biz"], s.exp["biz"], s.problems), (0, 0, []))

    def test_proviso_half_of_business_period(self) -> None:
        # 所令165①ただし書一：年の中途の開業（7月1日）なら、従事できた期間（6か月）の2分の1を超える従事（4か月）で足りる
        ctx, pay = _employee_ctx(400_000, 100_000, months=("2026-09-01", "2026-12-31"), biz_from="2026-07-01")
        s = _Sides()
        _family_employees(ctx, "p", s, {"b-p": "biz"}, {"b-p": [pay]}, None, {}, ["b-p"])
        self.assertEqual((s.salary["biz"], s.missing), (400_000, []))


def _proc(rid: str, procedure: str, on: str, **attrs: Any) -> dict[str, Any]:
    return {"id": rid, "kind": "blue_return_procedure", "roles": {"person": "p"}, "when": {"on": on}, "attributes": {"procedure": procedure, **attrs}}


class BlueStateTest(unittest.TestCase):
    def _state(self, *procs: dict[str, Any]) -> tuple[str | None, list[Any]]:
        ctx = YearContext(make_ir([person("p", "1960-01-01")], list(procs)), 2026, ("p",))
        splits: list[Any] = []
        state, _, _ = blue_state(ctx, "p", splits=splits)
        return state, splits

    def test_late_application_is_evaluated_both_ways(self) -> None:
        # 所法144 の期限（3月15日）の後の申請：どの年分からの承認かの一次情報がない → 承認なしの値に分かれ目を付ける
        state, splits = self._state(_proc("a-1", "application_filed", "2026-04-01", first_tax_year=2026))
        self.assertEqual((state, [s.id for s in splits]), (BLUE_NOT_APPROVED, ["一次情報:期限後の青色申告の申請:a-1"]))

    def test_inheritance_deadline(self) -> None:
        # 所基通144−1・A1-8：相続の開始（6月10日：1月〜8月）から4か月以内（10月10日）。所法144 の期限（開始から2月：8月10日）の後なので、
        # 被相続人が青色か（語彙がない）で分かれる
        state, splits = self._state(_proc("a-2", "application_filed", "2026-09-30", first_tax_year=2026, business_start_on="2026-06-10", succession_by_inheritance=True))
        self.assertEqual((state, len(splits)), (BLUE_NOT_APPROVED, 1))
        state, splits = self._state(_proc("a-3", "application_filed", "2026-08-01", first_tax_year=2026, business_start_on="2026-06-10", succession_by_inheritance=True))
        self.assertEqual((state, splits), (BLUE_APPROVED, []))


class VocabularyLinks20261112Test(unittest.TestCase):
    """2026-11-12 に足した語彙（所法56 の受取側の給与・結びつき・従事の期間・被相続人の青色・優良な電子帳簿・消費税等の内訳）の境目。"""

    def test_inheritance_with_decedent_blue_flag(self) -> None:
        # 所基通144−1：被相続人が青色（decedent_blue_approved）なら4か月の期限内で承認
        proc = _proc("a-2", "application_filed", "2026-09-30", first_tax_year=2026, business_start_on="2026-06-10", succession_by_inheritance=True, decedent_blue_approved=True)
        ctx = YearContext(make_ir([person("p", "1960-01-01")], [proc]), 2026, ("p",))
        splits: list[Any] = []
        self.assertEqual((blue_state(ctx, "p", splits=splits)[0], splits), (BLUE_APPROVED, []))

    def test_available_period_decides_proviso(self) -> None:
        # 所令165①ただし書二：従事することができた期間（7月〜12月の6か月）の2分の1を超える4か月の従事で足りる
        ctx, pay = _employee_ctx(400_000, 100_000, months=("2026-09-01", "2026-12-31"))
        facts = [dict(f) for f in ctx.ir["facts"]]
        g = next(f for f in facts if f["id"] == "g-1")
        g["attributes"] = {**g["attributes"], "interruption_reason": "long_illness", "available_period": {"from_on": "2026-07-01", "to_on": "2026-12-31"}}
        ctx2 = _ctx({**ctx.ir, "facts": facts}, {(K_JIGYO, "p:b-p"): True})
        s = _Sides()
        _family_employees(ctx2, "p", s, {"b-p": "biz"}, {"b-p": [pay]}, None, {}, ["b-p"])
        self.assertEqual((s.salary["biz"], s.missing), (400_000, []))

    def _salary_case(self) -> dict[str, Any]:
        persons, relations = _family()
        facts = [
            {"id": "b-p", "kind": "business", "roles": {"owner": "p"}, "when": {"from_on": "2020-01-01"}, "attributes": {}},
            {"id": "s-1", "kind": "business_receipt", "roles": {"recipient": "p"}, "when": {"on": "2026-05-01"}, "amounts": {"amount": 5_000_000}, "attributes": {"business_id": "b-p"}},
            {"id": "w-1", "kind": "payroll_paid", "roles": {"employer": "p", "recipient": "q"}, "when": {"on": "2026-12-20"}, "amounts": {"amount": 1_000_000}, "attributes": {"business_id": "b-p", "pay_type": "wages"}},
            {
                "id": "sp-1", "kind": "salary_payment", "roles": {"recipient": "q", "payer": "p"}, "when": {"on": "2026-12-20"}, "amounts": {"gross": 1_000_000},
                "attributes": {"counterparty": "架空の父の商店", "due_on": "2026-12-20", "payer_business_id": "b-p"},
            },
        ]
        return make_ir(persons, facts, relations=relations)

    def test_family_salary_from_white_business_is_excluded(self) -> None:
        # 所法56：白色の事業から生計を一にする子への給与は必要経費にならず、子の給与所得の計算上ないものとみなす（fudosan §5.1）
        out = ModuleInputs()
        _business(_ctx(self._salary_case(), {(K_JIGYO, "p:b-p"): True}), out)
        self.assertEqual((_value(out, V_FAMILY_SALARY_OUT, "q").value, _value(out, V_BIZ_EXP, "p").value), (1_000_000, 0))

    def test_family_salary_not_same_livelihood_is_kept(self) -> None:
        # 生計を一にしない親族への給与は通常の給与（所法56 の外）：含めない額は0
        out = ModuleInputs()
        _business(_ctx(self._salary_case(), {(K_JIGYO, "p:b-p"): True, (K_SEIKEI, "p:q"): False}), out)
        self.assertEqual(_value(out, V_FAMILY_SALARY_OUT, "q").value, 0)

    def test_land_interest_by_loan(self) -> None:
        # 措法41の4①：利子の支出が指す借入れ（loan_id）の目的の資産が土地等なら、その利子だけが土地等の負債の利子
        i1 = {"id": "i-1", "kind": "business_expense", "roles": {"payer": "p"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 30_000}, "attributes": {"expense_category": "loan_interest", "loan_id": "l-1"}}
        i2 = {"id": "i-2", "kind": "business_expense", "roles": {"payer": "p"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 70_000}, "attributes": {"expense_category": "loan_interest", "loan_id": "l-2"}}
        assets = [
            {"id": "rp-l", "kind": "rental_property", "roles": {"owner": "p"}, "when": {"from_on": "2015-01-01"}, "attributes": {"property_type": "land"}},
            {"id": "rp-b", "kind": "rental_property", "roles": {"owner": "p"}, "when": {"from_on": "2015-01-01"}, "attributes": {"property_type": "building"}},
            {"id": "l-1", "kind": "loan", "roles": {"borrower": "p"}, "when": {"from_on": "2015-01-01"}, "amounts": {"principal": 1}, "attributes": {"purpose_asset_id": "rp-l"}},
            {"id": "l-2", "kind": "loan", "roles": {"borrower": "p"}, "when": {"from_on": "2015-01-01"}, "amounts": {"principal": 1}, "attributes": {"purpose_asset_id": "rp-b"}},
        ]
        ctx = YearContext(make_ir([person("p", "1960-01-01")], [i1, i2], assets=assets), 2026, ("p",))
        self.assertEqual(_land_interest_by_loan(ctx, [i1, i2]), 30_000)
        self.assertIsNone(_land_interest_by_loan(ctx, [i1, {**i2, "attributes": {"expense_category": "loan_interest"}}]))

    def test_villa_by_property(self) -> None:
        # 所法69②：物件ごとの収支（property_id）で別荘等の分を求める。物件に結びつかない支出があれば決めない
        facts = [
            {"id": "f-1", "kind": "rent_flow", "roles": {"recipient": "p"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 100_000}, "attributes": {"flow_type": "rent", "property_id": "rp-v"}},
            {"id": "f-2", "kind": "rent_flow", "roles": {"recipient": "p"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 300_000}, "attributes": {"flow_type": "rent", "property_id": "rp-o"}},
        ]
        assets = [
            {"id": "rp-v", "kind": "rental_property", "roles": {"owner": "p"}, "when": {"from_on": "2015-01-01"}, "attributes": {"property_type": "building", "held_as_villa": True}},
            {"id": "rp-o", "kind": "rental_property", "roles": {"owner": "p"}, "when": {"from_on": "2015-01-01"}, "attributes": {"property_type": "room"}},
        ]
        ctx = YearContext(make_ir([person("p", "1960-01-01")], facts, assets=assets), 2026, ("p",))
        s = _Sides()
        s.rev["rental"], s.exp["rental"] = 400_000, 600_000
        s.prop_exp = {"rp-v": 500_000, "rp-o": 100_000}
        self.assertEqual(_villa_by_property(ctx, "p", s), (-400_000, 200_000))
        s.prop_exp = {"rp-v": 500_000, None: 100_000}
        self.assertIsNone(_villa_by_property(ctx, "p", s))

    def test_ebooks_filing_is_65(self) -> None:
        # 措法25の2④一：優良な電子帳簿で備え付け・保存し届出をした書面の申告は第4項の額（aoiro §3.1）
        r = BlueRules(basic=100_000, full=550_000, etax=650_000)
        self.assertEqual((blue_deduction(True, 3_000_000, True, FILING_EBOOKS, r), blue_deduction(True, 3_000_000, True, FILING_PAPER, r)), (650_000, 550_000))

    def test_ct_breakdown_by_business(self) -> None:
        # 業務ごとの消費税等の額（ct_return.attributes.business_breakdown）：合計が申告書と合えば業務ごと、合わなければ入力の矛盾
        rows = [{"business_id": "b-1", "consumption_tax": 60_000}, {"business_id": "b-2", "consumption_tax": 40_000}]
        ct = {
            "id": "ct-1", "kind": "ct_return", "roles": {"person": "p"}, "when": {"from_on": "2025-01-01", "to_on": "2025-12-31"},
            "amounts": {"consumption_tax": 100_000}, "attributes": {"return_type": "final", "filed_or_decided_on": "2026-03-10", "business_breakdown": rows},
        }
        plan = CtPlan("all", methods={"b-1": INCLUSIVE, "b-2": INCLUSIVE}, accrue={"b-1": False, "b-2": False}, prior_accrued={"b-1": False, "b-2": False})
        per, _, problems = tax_expense_by_business(YearContext(make_ir([person("p", "1960-01-01")], [ct]), 2026, ("p",)), "p", plan, ["b-1", "b-2"])
        self.assertEqual((per, problems), ({"b-1": 60_000, "b-2": 40_000}, []))
        bad = {**ct, "attributes": {**ct["attributes"], "business_breakdown": [rows[0], {"business_id": "b-2", "consumption_tax": 30_000}]}}
        per, _, problems = tax_expense_by_business(YearContext(make_ir([person("p", "1960-01-01")], [bad]), 2026, ("p",)), "p", plan, ["b-1", "b-2"])
        self.assertEqual((per, len(problems)), ({}, 1))


class ReceiverDepreciation56Test(unittest.TestCase):
    """IK-32 の残り（2026-11-12）：受取側の減価償却費のうち、親族の事業から受けた対価（売上）に係る部分は depreciable_asset の receipt_id で決める
    （所法56 後段：fudosan §5.1。business_expense の receipt_id と同じ読み）。耐用年数5年の定額法の償却率 0.200（別表第八：docs/public-sources/20261109_round2_genka-laws-and-nta.md §2.2）。"""

    def _case(self, *, receipt_of_a2: str | None = None) -> dict[str, Any]:
        persons, relations = _family()
        facts = [
            {"id": "b-p", "kind": "business", "roles": {"owner": "p"}, "when": {"from_on": "2020-01-01"}, "attributes": {}},
            {"id": "b-q", "kind": "business", "roles": {"owner": "q"}, "when": {"from_on": "2020-01-01"}, "attributes": {}},
            {"id": "s-1", "kind": "business_receipt", "roles": {"recipient": "p"}, "when": {"on": "2026-05-01"}, "amounts": {"amount": 5_000_000}, "attributes": {"business_id": "b-p"}},
            {"id": "s-q1", "kind": "business_receipt", "roles": {"recipient": "q"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 1_000_000}, "attributes": {"business_id": "b-q"}},
            {"id": "s-q2", "kind": "business_receipt", "roles": {"recipient": "q"}, "when": {"on": "2026-07-01"}, "amounts": {"amount": 500_000}, "attributes": {"business_id": "b-q"}},
            {"id": "e-1", "kind": "business_expense", "roles": {"payer": "p", "payee": "q"}, "when": {"on": "2026-06-01"}, "amounts": {"amount": 1_000_000},
             "attributes": {"business_id": "b-p", "expense_category": "outsourcing", "receipt_id": "s-q1"}},
        ]  # fmt: skip
        a2 = {"name": "架空の器具B", "business_id": "b-q", **({"receipt_id": receipt_of_a2} if receipt_of_a2 else {})}
        assets = [
            {"id": "a-1", "kind": "depreciable_asset", "roles": {"owner": "q"}, "when": {"from_on": "2025-01-01"}, "amounts": {"acquisition_cost": 1_000_000},
             "attributes": {"name": "架空の器具A", "business_id": "b-q", "receipt_id": "s-q1"}},
            {"id": "a-2", "kind": "depreciable_asset", "roles": {"owner": "q"}, "when": {"from_on": "2025-01-01"}, "amounts": {"acquisition_cost": 500_000}, "attributes": a2},
        ]  # fmt: skip
        judgments = [
            {"id": f"dc-{a}", "kind": "判断.減価償却の区分", "subject": {"asset_id": a}, "value": {"useful_life_years": 5}} for a in ("a-1", "a-2")
        ]
        return make_ir(persons, facts, relations=relations, assets=assets, judgments=judgments)

    def test_only_assets_pointing_the_receipt_move(self) -> None:
        out = ModuleInputs()
        _business(_ctx(self._case(), {(K_JIGYO, "p:b-p"): True, (K_JIGYO, "q:b-q"): True}), out)
        self.assertEqual((_value(out, V_BIZ_DEP, "p").value, _value(out, V_BIZ_DEP, "q").value), (200_000, 100_000))
        self.assertEqual(_value(out, V_BIZ_REV, "q").value, 500_000)  # 親族の事業からの対価の売上はないものとみなす
        self.assertEqual((_value(out, V_BIZ_DEP, "p").missing, _value(out, V_BIZ_DEP, "q").missing), ((), ()))
        self.assertEqual(out.exclusions, [])

    def test_asset_pointing_another_sides_receipt_is_input_error(self) -> None:
        # 資産の receipt_id が指す売上と資産の業務の所得の側が違えば記録の矛盾（c-入力）
        ir = self._case()
        ir["facts"].append({"id": "b-q2", "kind": "business", "roles": {"owner": "q"}, "when": {"from_on": "2020-01-01"}, "attributes": {}})
        ir["assets"][0]["attributes"]["business_id"] = "b-q2"
        out = ModuleInputs()
        _business(_ctx(ir, {(K_JIGYO, "p:b-p"): True, (K_JIGYO, "q:b-q"): True, (K_JIGYO, "q:b-q2"): False}), out)
        self.assertIn(LINK_56_SIDE_REASON, {e.reason.reason for e in out.exclusions})

if __name__ == "__main__":
    unittest.main()
